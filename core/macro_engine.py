"""
MacroX — Macro Execution Engine

Architecture:
  MacroEngine (singleton)
    ├── HotkeyListener thread  — pynput global listener, maps hotkeys → macros
    └── MacroRunner thread(s)  — one per active macro, executes steps

Modes:
  0 = Once        — press → run once → done
  1 = Hold        — press → loop while key held → release → stop
  2 = Toggle      — first press → start loop, second press → stop

Hotkey format (same as HotkeyCapture uses):
  Keyboard:  "A", "F1", "CTRL+SHIFT+A", "SPACE", "ESCAPE"
  Mouse:     "Mouse1"-"Mouse5"

Condition system (Этап 3):
  Macro-level (Variant A):
    macro["condition"] = {
        "zone_id": N,        # zone to check
        "state":   "match"   # "match" | "no_match"
    }
    If condition is not met when hotkey fires — macro is skipped entirely.

  Step-level (Variant B):
    step["condition"] = {
        "zone_id": N,
        "state":   "match"
    }
    step["condition_action"] = "skip" | "stop"
    If condition is not met — step is skipped (or macro is stopped).

  Both can be combined freely.
"""

import time, logging, threading, random
from PyQt6.QtCore import QObject, pyqtSignal
from core.logger import trace_calls
from core.macro_store import get_store

log = logging.getLogger(__name__)


# ── Engine-level Qt signals ───────────────────────────────────────────────────
class _EngineSignals(QObject):
    macro_started        = pyqtSignal(str)           # macro name
    macro_stopped        = pyqtSignal(str)           # macro name
    active_count_changed = pyqtSignal(int)           # number of currently running macros
    step_executed        = pyqtSignal(str, str, int) # macro_name, key, delay_ms
    step_skipped         = pyqtSignal(str, str)      # macro_name, key (condition not met)

# Lazily created after QApplication exists — avoids thread-affinity issues
_engine_signals_instance: "_EngineSignals | None" = None

def _get_signals() -> "_EngineSignals":
    global _engine_signals_instance
    if _engine_signals_instance is None:
        _engine_signals_instance = _EngineSignals()
    return _engine_signals_instance

# Public alias — safe to import, actual object created on first use
class _SignalsProxy:
    """Proxy that forwards attribute access to the lazily-created signals object."""
    def __getattr__(self, name):
        return getattr(_get_signals(), name)

engine_signals = _SignalsProxy()


def _journal_macro_started(macro_id: int, macro_name: str):
    """Вызывается напрямую из MacroRunner — как on_monitor_trigger в monitor_engine."""
    try:
        from core.journal import get_journal
        get_journal().on_macro_started(macro_id, macro_name)
    except Exception as e:
        log.error(f"_journal_macro_started: {e}", exc_info=True)

def _journal_macro_stopped(macro_id: int, macro_name: str):
    try:
        from core.journal import get_journal
        get_journal().on_macro_stopped(macro_id, macro_name)
    except Exception as e:
        log.error(f"_journal_macro_stopped: {e}", exc_info=True)

def _journal_step_executed(macro_id: int, macro_name: str, key: str, delay_ms: int):
    try:
        from core.journal import get_journal
        get_journal().on_step_executed(macro_id, macro_name, key, delay_ms)
    except Exception as e:
        log.error(f"_journal_step_executed: {e}", exc_info=True)

def _journal_macro_skipped(macro_id: int, macro_name: str):
    try:
        from core.journal import get_journal
        get_journal().on_macro_skipped(macro_id, macro_name)
    except Exception as e:
        log.error(f"_journal_macro_skipped: {e}", exc_info=True)

def _journal_step_skipped(macro_id: int, macro_name: str, key: str, action: str):
    try:
        from core.journal import get_journal
        get_journal().on_step_skipped(macro_id, macro_name, key, action)
    except Exception as e:
        log.error(f"_journal_step_skipped: {e}", exc_info=True)

def _connect_journal():
    pass  # journal is written directly from MacroRunner (see _journal_macro_* above)


def _get_id_by_name(name: str) -> int:
    """Reverse-lookup macro id from name (best-effort, uses first match)."""
    try:
        eng = get_engine()
        for mid, m in eng._macros.items():
            if m.get("name") == name:
                return mid
    except Exception:
        pass
    return -1


# ── Condition checkers ───────────────────────────────────────────────────────

def _check_zone_condition(condition: dict | None) -> bool:
    """
    Evaluate a condition dict against the current MonitorEngine zone state.
    Returns True if condition passes (or if no condition is set).

    condition = {"zone_id": N, "state": "match" | "no_match"}
    """
    if not condition:
        return True
    zone_id  = condition.get("zone_id")
    expected = condition.get("state", "match")
    if zone_id is None:
        return True
    try:
        from core.monitor_engine import get_monitor_engine
        engine = get_monitor_engine()
        thread = engine._thread
        if thread is None:
            log.debug(f"Condition check: monitor not running → pass through")
            return True
        worker = thread._workers.get(zone_id)
        if worker is None:
            log.debug(f"Condition check: zone_id={zone_id} not found in workers → pass through")
            return True
        actual = worker._last_state
        result = (actual == expected)
        log.debug(f"Condition check: zone_id={zone_id} expected={expected} actual={actual} → {result}")
        return result
    except Exception as e:
        log.warning(f"_check_zone_condition: {e} → pass through")
        return True


def _check_state_condition(condition: dict) -> bool:
    """
    Evaluate a condition dict against StateStore.
    condition = {"state_var": "hp_pct", "op": "<=", "value": 30}
    """
    try:
        from core.state_store import get_state_store
        result = get_state_store().evaluate(condition)
        log.debug(f"_check_state_condition: {condition} → {result}")
        return result
    except Exception as e:
        log.warning(f"_check_state_condition: {e} → pass through")
        return True


def _check_condition(condition: dict | None) -> bool:
    """
    Unified condition checker: routes to zone or state checker based on condition type.
    condition = {"zone_id": N, "state": "match"}       → zone check
    condition = {"state_var": "hp_pct", "op": "<=", "value": 30} → state check
    """
    if not condition:
        return True
    if "state_var" in condition:
        return _check_state_condition(condition)
    return _check_zone_condition(condition)


# ── Step executor ─────────────────────────────────────────────────────────────
def _execute_steps(steps: list[dict], stop_event: threading.Event,
                   macro_name: str = "", kb=None, ms=None,
                   macro_id: int = -1) -> bool:
    """
    Send keystrokes/clicks for one pass through steps.
    Stops if stop_event is set.

    Accepts optional pre-created kb/ms controllers to avoid
    re-creating them on every call in Hold/Toggle loops.

    Returns False if macro-stop was requested via step condition.
    """
    try:
        from pynput.keyboard import Controller as KbCtrl, KeyCode, Key
        from pynput.mouse   import Controller as MsCtrl, Button
        from ui._pynput_compat import build_mouse_map
    except ImportError:
        log.error("pynput not available — cannot execute macro")
        return True

    # Reuse controllers if provided (Hold/Toggle perf fix)
    if kb is None:
        kb = KbCtrl()
    if ms is None:
        ms = MsCtrl()

    MOUSE_MAP_INV = {v: k for k, v in build_mouse_map().items()}

    MOD_KEYS = {
        "CTRL":  Key.ctrl,
        "SHIFT": Key.shift,
        "ALT":   Key.alt,
        "WIN":   Key.cmd,
    }

    for step in steps:
        if stop_event.is_set():
            return True

        # ── Step-level condition (Variant B) ──────────────────────────────
        step_cond = step.get("condition")
        if step_cond:
            if not _check_condition(step_cond):
                cond_action = step.get("condition_action", "skip")
                key_str     = step.get("key", "")
                log.info(f"Step condition not met: key='{key_str}' action={cond_action}")
                _mid = macro_id if macro_id >= 0 else _get_id_by_name(macro_name)
                _journal_step_skipped(_mid, macro_name, key_str, cond_action)
                try:
                    engine_signals.step_skipped.emit(macro_name, key_str)
                except Exception:
                    pass
                if cond_action == "stop":
                    return False   # signal caller to stop the macro
                continue           # skip this step

        delay_ms = step.get("delay_ms", 0)
        if delay_ms > 0:
            slept = 0
            while slept < delay_ms and not stop_event.is_set():
                chunk = min(20, delay_ms - slept)
                time.sleep(chunk / 1000.0)
                slept += chunk
            if stop_event.is_set():
                return True

        key_str = step.get("key", "")
        _press_key(kb, ms, key_str, MOD_KEYS, MOUSE_MAP_INV)
        _dms = step.get("delay_ms", 0)
        _mid = macro_id if macro_id >= 0 else _get_id_by_name(macro_name)
        _journal_step_executed(_mid, macro_name, key_str, _dms)
        try:
            engine_signals.step_executed.emit(macro_name, key_str, _dms)
        except Exception:
            pass

    return True


# ── Windows SendInput — works with DirectInput/Raw Input games ───────────────
_WIN_VK = {
    "SPACE":0x20,"ENTER":0x0D,"RETURN":0x0D,"TAB":0x09,
    "ESCAPE":0x1B,"ESC":0x1B,"BACKSPACE":0x08,
    "DELETE":0x2E,"DEL":0x2E,"INSERT":0x2D,
    "HOME":0x24,"END":0x23,"PAGEUP":0x21,"PAGEDOWN":0x22,
    "LEFT":0x25,"UP":0x26,"RIGHT":0x27,"DOWN":0x28,
    "F1":0x70,"F2":0x71,"F3":0x72,"F4":0x73,"F5":0x74,"F6":0x75,
    "F7":0x76,"F8":0x77,"F9":0x78,"F10":0x79,"F11":0x7A,"F12":0x7B,
    "NUMPAD0":0x60,"NUMPAD1":0x61,"NUMPAD2":0x62,"NUMPAD3":0x63,
    "NUMPAD4":0x64,"NUMPAD5":0x65,"NUMPAD6":0x66,"NUMPAD7":0x67,
    "NUMPAD8":0x68,"NUMPAD9":0x69,"NUMLOCK":0x90,"CAPSLOCK":0x14,
    "LSHIFT":0xA0,"RSHIFT":0xA1,"LCTRL":0xA2,"RCTRL":0xA3,
    "CTRL":0x11,"SHIFT":0x10,"ALT":0x12,"WIN":0x5B,
}

def _vk_for(name: str) -> int | None:
    upper = name.upper()
    if upper in _WIN_VK:
        return _WIN_VK[upper]
    if len(name) == 1:
        try:
            import ctypes
            res = ctypes.windll.user32.VkKeyScanW(ord(name.upper()))
            vk  = res & 0xFF
            return vk if vk != 0xFF else None
        except Exception:
            pass
    return None

def _send_input_key(key_str: str) -> bool:
    try:
        import ctypes, ctypes.wintypes as _wt

        class _KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk",_wt.WORD),("wScan",_wt.WORD),
                        ("dwFlags",_wt.DWORD),("time",_wt.DWORD),
                        ("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
        class _IU(ctypes.Union):
            _fields_ = [("ki",_KEYBDINPUT),("_p",ctypes.c_byte*28)]
        class _INPUT(ctypes.Structure):
            _fields_ = [("type",_wt.DWORD),("u",_IU)]

        KEYUP = 0x0002
        SCAN  = 0x0008
        KBD   = 1

        def _send(vk: int, up: bool):
            scan  = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
            flags = SCAN | (KEYUP if up else 0)
            inp   = _INPUT(type=KBD, u=_IU(ki=_KEYBDINPUT(
                wVk=0, wScan=scan, dwFlags=flags, time=0,
                dwExtraInfo=ctypes.pointer(ctypes.c_ulong(0)))))
            ctypes.windll.user32.SendInput(
                1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

        parts   = key_str.split("+")
        mods    = [p.upper() for p in parts[:-1] if p.upper() in _WIN_VK]
        base    = parts[-1]
        vk_base = _vk_for(base)
        if vk_base is None:
            return False

        for m in mods:          _send(_WIN_VK[m], False)
        _send(vk_base, False)
        _send(vk_base, True)
        for m in reversed(mods): _send(_WIN_VK[m], True)

        log.debug(f"Exec key (SendInput/scan): {key_str}")
        return True
    except Exception as e:
        log.debug(f"SendInput failed for '{key_str}': {e}")
        return False


def _press_key(kb, ms, key_str: str, MOD_KEYS: dict, MOUSE_MAP_INV: dict):
    from pynput.keyboard import KeyCode, Key
    if not key_str:
        return
    if key_str in MOUSE_MAP_INV:
        btn = MOUSE_MAP_INV[key_str]
        ms.click(btn)
        log.debug(f"Exec mouse: {key_str}")
        return
    if _send_input_key(key_str):
        return
    parts = key_str.split("+")
    mods  = [MOD_KEYS[p] for p in parts[:-1] if p in MOD_KEYS]
    base  = parts[-1]
    for m in mods:
        kb.press(m)
    pkey = _resolve_key(base)
    if pkey is not None:
        try:
            kb.press(pkey)
            kb.release(pkey)
        except Exception as e:
            log.warning(f"pynput key press failed for '{base}': {e}")
    for m in reversed(mods):
        kb.release(m)
    log.debug(f"Exec key (pynput): {key_str}")


def _resolve_key(name: str):
    from pynput.keyboard import KeyCode, Key
    if len(name) == 1:
        return KeyCode.from_char(name.lower())
    SPECIAL = {
        "SPACE":     Key.space,  "ENTER":      Key.enter,
        "RETURN":    Key.enter,  "TAB":        Key.tab,
        "ESCAPE":    Key.esc,    "ESC":        Key.esc,
        "BACKSPACE": Key.backspace, "DELETE":  Key.delete,
        "DEL":       Key.delete, "INSERT":     Key.insert,
        "HOME":      Key.home,   "END":        Key.end,
        "PAGE_UP":   Key.page_up,"PAGE_DOWN":  Key.page_down,
        "UP":        Key.up,     "DOWN":       Key.down,
        "LEFT":      Key.left,   "RIGHT":      Key.right,
        "CAPS_LOCK": Key.caps_lock, "NUM_LOCK":Key.num_lock,
        "PRINT_SCREEN": Key.print_screen,
        "SCROLL_LOCK":  Key.scroll_lock,
        "PAUSE":     Key.pause,  "MENU":       Key.menu,
        "CTRL":      Key.ctrl,   "SHIFT":      Key.shift,
        "ALT":       Key.alt,    "WIN":        Key.cmd,
        "CMD":       Key.cmd,
    }
    if name in SPECIAL:
        return SPECIAL[name]
    if name.startswith("F") and name[1:].isdigit():
        fkey = getattr(Key, f"f{int(name[1:])}", None)
        if fkey: return fkey
    if name.startswith("NUM_"):
        rest = name[4:]
        if rest.isdigit():
            return KeyCode.from_char(rest)
    try:
        return KeyCode.from_char(name.lower())
    except Exception:
        log.warning(f"Unknown key: '{name}'")
        return None


# ── MacroRunner thread ────────────────────────────────────────────────────────
class MacroRunner(threading.Thread):
    """
    Runs a single macro according to its mode.

    Fix: controllers created once in __init__ — not per-iteration.
    Fix: _running flag cleared only after thread fully exits.
    Fix: macro_stopped signal emitted only if macro was actually running.
    """

    def __init__(self, macro: dict, on_done=None):
        super().__init__(daemon=True, name=f"Runner-{macro.get('name','?')}")
        self.macro      = macro
        self._stop      = threading.Event()
        self._hold_flag = threading.Event()
        self._running   = False
        self._on_done   = on_done   # callback(macro_id) called when runner finishes naturally
        # Pre-create controllers (reused across iterations in Hold/Toggle)
        self._kb = None
        self._ms = None

    def _init_controllers(self):
        """Lazy-init input controllers inside the runner thread."""
        try:
            from pynput.keyboard import Controller as KbCtrl
            from pynput.mouse   import Controller as MsCtrl
            self._kb = KbCtrl()
            self._ms = MsCtrl()
        except Exception as e:
            log.error(f"Controller init failed: {e}")

    def signal_key_down(self):
        self._hold_flag.set()

    def signal_key_up(self):
        self._hold_flag.clear()

    def stop(self):
        self._stop.set()
        self._hold_flag.clear()

    def is_running(self) -> bool:
        return self._running and self.is_alive()   # Fix: both flags must be true

    def run(self):
        self._running = True
        self._init_controllers()

        mode  = self.macro.get("mode", 0)
        steps = self.macro.get("steps", [])
        name  = self.macro.get("name", "?")
        mid   = self.macro.get("id", -1)
        log.info(f"MacroRunner start: '{name}'  mode={mode}  steps={len(steps)}")

        _journal_macro_started(mid, name)
        try:
            engine_signals.macro_started.emit(name)
            engine_signals.active_count_changed.emit(1)
        except Exception:
            pass

        skipped_by_condition = False
        try:
            macro_cond = self.macro.get("condition")
            if macro_cond and not _check_condition(macro_cond):
                log.info(f"MacroRunner '{name}': macro condition not met → skip")
                skipped_by_condition = True
                _journal_macro_skipped(mid, name)
            else:
                if mode == 0:   self._run_once(steps, name, mid)
                elif mode == 1: self._run_hold(steps, name, mid)
                elif mode == 2: self._run_toggle(steps, name, mid)
        except Exception as e:
            log.error(f"MacroRunner '{name}' error: {e}", exc_info=True)

        self._running = False
        log.info(f"MacroRunner done: '{name}'")

        if not skipped_by_condition:
            _journal_macro_stopped(mid, name)
        if not self._stop.is_set() and not skipped_by_condition:
            try:
                engine_signals.macro_stopped.emit(name)
                engine_signals.active_count_changed.emit(0)
            except Exception:
                pass

        # Clean up from engine's _runners map
        if self._on_done:
            try:
                self._on_done(mid)
            except Exception:
                pass

    def _run_once(self, steps, name, mid=-1):
        _execute_steps(steps, self._stop, name, self._kb, self._ms, mid)

    def _run_hold(self, steps, name, mid=-1):
        delay_ms  = self.macro.get("delay_ms", 100)
        random_ms = self.macro.get("random_ms", 0)
        while self._hold_flag.is_set() and not self._stop.is_set():
            should_continue = _execute_steps(
                steps, self._stop, name, self._kb, self._ms, mid)
            if not should_continue or self._stop.is_set():
                break
            total = (delay_ms + random.randint(-random_ms, random_ms)
                     if random_ms else delay_ms)
            total = max(0, total)
            slept = 0
            while slept < total and self._hold_flag.is_set() and not self._stop.is_set():
                chunk = min(20, total - slept)
                time.sleep(chunk / 1000.0)
                slept += chunk

    def _run_toggle(self, steps, name, mid=-1):
        delay_ms  = self.macro.get("delay_ms", 100)
        random_ms = self.macro.get("random_ms", 0)
        while not self._stop.is_set():
            should_continue = _execute_steps(
                steps, self._stop, name, self._kb, self._ms, mid)
            if not should_continue or self._stop.is_set():
                break
            total = (delay_ms + random.randint(-random_ms, random_ms)
                     if random_ms else delay_ms)
            total = max(0, total)
            slept = 0
            while slept < total and not self._stop.is_set():
                chunk = min(20, total - slept)
                time.sleep(chunk / 1000.0)
                slept += chunk


# ── Hotkey listener thread ────────────────────────────────────────────────────
class HotkeyListener(threading.Thread):
    def __init__(self, on_press, on_release):
        super().__init__(daemon=True, name="HotkeyListener")
        self._on_press   = on_press
        self._on_release = on_release
        self._quit       = threading.Event()
        self._held: set  = set()

    def stop(self):
        self._quit.set()

    def run(self):
        log.info("HotkeyListener starting")
        try:
            from pynput import keyboard, mouse as pmouse
            from ui._pynput_compat import build_mouse_map
            MOUSE_MAP     = build_mouse_map()
            MOUSE_MAP_INV = {v: k for k, v in MOUSE_MAP.items()}

            MOD_MAP = {
                keyboard.Key.shift:   "SHIFT",
                keyboard.Key.shift_r: "SHIFT",
                keyboard.Key.ctrl:    "CTRL",
                keyboard.Key.ctrl_r:  "CTRL",
                keyboard.Key.alt:     "ALT",
                keyboard.Key.alt_r:   "ALT",
                keyboard.Key.alt_gr:  "ALT",
            }
            for attr in ("cmd", "cmd_r"):
                try: MOD_MAP[getattr(keyboard.Key, attr)] = "WIN"
                except AttributeError: pass

            def _key_to_str(key) -> str:
                if key in MOD_MAP:
                    return MOD_MAP[key]
                try:
                    return (key.char.upper()
                            if (hasattr(key, "char") and key.char)
                            else key.name.upper())
                except Exception:
                    return str(key).upper().strip("'<>")

            def _build_combo(base: str) -> str:
                mods = sorted(m for k, m in MOD_MAP.items() if k in self._held)
                seen: set = set()
                unique_mods = []
                for m in mods:
                    if m not in seen:
                        seen.add(m); unique_mods.append(m)
                return "+".join(unique_mods + [base]) if unique_mods else base

            def kb_press(key):
                if self._quit.is_set(): return False
                self._held.add(key)
                if key in MOD_MAP: return
                combo = _build_combo(_key_to_str(key))
                self._on_press(combo)

            def kb_release(key):
                self._held.discard(key)
                if key in MOD_MAP: return
                combo = _build_combo(_key_to_str(key))
                self._on_release(combo)

            def ms_click(x, y, button, pressed):
                if self._quit.is_set(): return False
                name = MOUSE_MAP.get(button, f"Mouse_{button.name}")
                if pressed: self._on_press(name)
                else:       self._on_release(name)

            kb_lst = keyboard.Listener(on_press=kb_press, on_release=kb_release)
            ms_lst = pmouse.Listener(on_click=ms_click)
            kb_lst.start(); ms_lst.start()
            log.info("HotkeyListener active")
            self._quit.wait()
            kb_lst.stop(); ms_lst.stop()
            log.info("HotkeyListener stopped")

        except ImportError:
            log.error("pynput missing — HotkeyListener cannot start")
        except Exception as e:
            log.error(f"HotkeyListener error: {e}", exc_info=True)


# ── MacroEngine singleton ─────────────────────────────────────────────────────
class MacroEngine:
    def __init__(self):
        self._lock       = threading.Lock()
        self._macros:    dict[int, dict]        = {}
        self._runners:   dict[int, MacroRunner] = {}
        self._listener:  HotkeyListener | None  = None
        self._hotkey_map: dict[str, list[int]]  = {}

    @trace_calls
    def start(self):
        if self._listener and self._listener.is_alive():
            log.warning("MacroEngine already running")
            return
        self._listener = HotkeyListener(
            on_press   = self._on_hotkey_press,
            on_release = self._on_hotkey_release,
        )
        self._listener.start()
        for m in get_store().all():
            self.register(m)
        _connect_journal()
        log.info(f"MacroEngine started. {len(self._macros)} macros loaded.")

    @trace_calls
    def stop(self):
        self._stop_all_runners()
        if self._listener:
            self._listener.stop()
            self._listener = None
        log.info("MacroEngine stopped")

    @trace_calls
    def register(self, macro: dict):
        mid = macro.get("id")
        if mid is None:
            log.warning("register: macro has no id"); return
        with self._lock:
            self._macros[mid] = macro
            self._rebuild_hotkey_map()
        log.info(f"Registered macro id={mid} name='{macro.get('name')}' "
                 f"hotkey='{macro.get('hotkey')}' active={macro.get('active')}")

    @trace_calls
    def unregister(self, macro_id: int):
        self._stop_runner(macro_id)
        with self._lock:
            self._macros.pop(macro_id, None)
            self._rebuild_hotkey_map()
        log.info(f"Unregistered macro id={macro_id}")

    @trace_calls
    def set_active(self, macro_id: int, active: bool):
        with self._lock:
            if macro_id in self._macros:
                self._macros[macro_id]["active"] = active
                self._rebuild_hotkey_map()
                if not active:
                    self._stop_runner(macro_id)
        log.info(f"Macro id={macro_id} active={active}")
        get_store().update(macro_id, {"active": active})

    def is_running(self, macro_id: int) -> bool:
        r = self._runners.get(macro_id)
        return r is not None and r.is_running()

    # ── Hotkey dispatch ───────────────────────────────────────────────────────
    def _on_hotkey_press(self, combo: str):
        with self._lock:
            ids = list(self._hotkey_map.get(combo, []))
        for mid in ids:
            macro = self._macros.get(mid)
            if not macro or not macro.get("active", False):
                continue
            mode = macro.get("mode", 0)
            log.debug(f"Hotkey '{combo}' pressed → macro id={mid} mode={mode}")
            if   mode == 0: self._trigger_once(mid)
            elif mode == 1: self._trigger_hold_start(mid)
            elif mode == 2: self._trigger_toggle(mid)

    def _on_hotkey_release(self, combo: str):
        with self._lock:
            ids = list(self._hotkey_map.get(combo, []))
        for mid in ids:
            macro = self._macros.get(mid)
            if not macro or not macro.get("active", False):
                continue
            if macro.get("mode", 0) == 1:
                log.debug(f"Hotkey '{combo}' released → stop Hold macro id={mid}")
                self._stop_runner(mid)
                runner = self._runners.get(mid)
                if runner:
                    runner.signal_key_up()

    def _trigger_once(self, mid: int):
        if self.is_running(mid):
            log.debug(f"Once macro id={mid} already running — skipped")
            return
        self._start_runner(mid)

    def _trigger_hold_start(self, mid: int):
        if self.is_running(mid): return
        runner = self._start_runner(mid)
        if runner:
            runner.signal_key_down()

    def _trigger_toggle(self, mid: int):
        if self.is_running(mid):
            log.debug(f"Toggle macro id={mid} — STOP")
            self._stop_runner(mid)
        else:
            log.debug(f"Toggle macro id={mid} — START")
            self._start_runner(mid)

    # ── Runner lifecycle ──────────────────────────────────────────────────────
    def _start_runner(self, mid: int) -> "MacroRunner | None":
        macro = self._macros.get(mid)
        if not macro:
            return None
        if macro.get("_monitor_toggle"):
            try:
                from core.monitor_engine import get_monitor_engine
                get_monitor_engine().toggle()
                log.info("Monitor engine toggled via hotkey")
            except Exception as e:
                log.error(f"Monitor toggle: {e}")
            return None

        def _on_runner_done(macro_id: int):
            """Called from runner thread when macro finishes naturally."""
            self._runners.pop(macro_id, None)
            try:
                engine_signals.active_count_changed.emit(len(self._runners))
            except Exception:
                pass

        runner = MacroRunner(macro, on_done=_on_runner_done)
        self._runners[mid] = runner
        runner.start()
        name = macro.get("name", "?")
        engine_signals.macro_started.emit(name)
        engine_signals.active_count_changed.emit(len(self._runners))
        log.debug(f"Runner started for '{name}', total active: {len(self._runners)}")
        return runner

    def _stop_runner(self, mid: int):
        runner = self._runners.pop(mid, None)
        if runner and runner.is_alive():   # Fix: only emit stopped if was alive
            runner.stop()
            name = self._macros.get(mid, {}).get("name", "?")
            engine_signals.macro_stopped.emit(name)
            engine_signals.active_count_changed.emit(len(self._runners))
            log.debug(f"Runner stopped for '{name}', total active: {len(self._runners)}")

    def _stop_all_runners(self):
        for mid in list(self._runners):
            self._stop_runner(mid)

    # ── Hotkey map ────────────────────────────────────────────────────────────
    def _rebuild_hotkey_map(self):
        """Must be called under self._lock."""
        hm: dict[str, list[int]] = {}
        for mid, macro in self._macros.items():
            if not macro.get("active", False):
                continue
            hk = macro.get("hotkey", "").strip()
            if not hk or hk == "—":
                continue
            hm.setdefault(hk, []).append(mid)
        self._hotkey_map = hm
        log.debug(f"Hotkey map rebuilt: {self._hotkey_map}")


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine: MacroEngine | None = None

def get_engine() -> MacroEngine:
    global _engine
    if _engine is None:
        _engine = MacroEngine()
    return _engine
