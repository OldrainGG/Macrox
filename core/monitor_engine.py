"""
MacroX — Monitor Engine v2

Features:
  - Priority queue: critical zones (p=1) fire before normal (p=2) before background (p=3)
  - Parallel flag per zone: bypass queue, fire immediately regardless of others
  - Scene-aware: only zones of active scene are evaluated
  - Transition detection: fires only on state CHANGE (match→no_match etc.)
  - Per-zone cooldown to prevent spam
  - Thread-safe Qt signals for UI updates
"""
import time, threading, logging, base64
from io import BytesIO
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


# ── Signals ───────────────────────────────────────────────────────────────────
class _MonitorSignals(QObject):
    zone_triggered  = pyqtSignal(int, str, float)   # zone_id, name, similarity
    zone_state      = pyqtSignal(int, str)           # zone_id, "match"|"no_match"|"error"
    engine_started  = pyqtSignal()
    engine_stopped  = pyqtSignal()
    scene_changed   = pyqtSignal(int)                # new scene_id

monitor_signals = _MonitorSignals()


# ── Image utilities ───────────────────────────────────────────────────────────
def _similarity(img_a, img_b) -> float:
    """
    Pixel-match similarity: fraction of pixels where each channel diff < tolerance.
    This maps much more intuitively to visual change:
      0.90 = 90% of pixels look the same → close match
      0.50 = half the pixels changed      → very different
    Tolerance=30/255 per channel (~12%) handles JPEG/rendering noise.
    """
    import numpy as np
    a = np.array(img_a.convert("RGB"), dtype=np.int16)
    b = np.array(img_b.convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        from PIL import Image
        b = np.array(
            img_b.resize((img_a.width, img_a.height), Image.LANCZOS).convert("RGB"),
            dtype=np.int16
        )
    tolerance = 30  # per-channel tolerance (0-255)
    diff      = np.abs(a - b)                          # shape: H×W×3
    match     = (diff < tolerance).all(axis=2)         # H×W bool: all 3 channels match
    return float(match.mean())                         # fraction of matching pixels


def capture_region(rect: list):
    try:
        import mss
        from PIL import Image
        x, y, w, h = rect
        with mss.mss() as sct:
            mon = {"left": x, "top": y, "width": max(1, w), "height": max(1, h)}
            raw = sct.grab(mon)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    except Exception as e:
        log.error(f"capture_region: {e}"); return None


def b64_to_image(b64: str):
    try:
        from PIL import Image
        return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception as e:
        log.error(f"b64_to_image: {e}"); return None


def image_to_b64(img) -> str:
    buf = BytesIO(); img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── Per-zone state tracker ────────────────────────────────────────────────────
class ZoneWorker:
    """
    Delegates evaluation to ZoneEvaluator (monitor_match.py).
    Supports both pixel similarity and template matching zone types,
    including debug_capture, extend_below_px, grid matching, and OCR.
    """
    def __init__(self, zone: dict):
        self.zone       = zone
        self._prev      = None
        self._last_fire = 0.0
        self._evaluator = None
        self._load_evaluator()

    def _load_evaluator(self):
        try:
            from core.monitor_match import ZoneEvaluator
            self._evaluator = ZoneEvaluator(self.zone)
        except Exception as e:
            log.error(f"ZoneEvaluator load: {e}")
            self._evaluator = None

    def update(self, zone: dict):
        self.zone = zone
        if self._evaluator:
            self._evaluator.update(zone)
        else:
            self._load_evaluator()

    def tick(self) -> tuple[str, float]:
        if not self._evaluator:
            # Fallback: plain pixel similarity (no monitor_match available)
            ref_b64 = self.zone.get("reference", "")
            if not ref_b64:
                return "error", 0.0
            ref = b64_to_image(ref_b64)
            if ref is None:
                return "error", 0.0
            cur = capture_region(self.zone.get("rect", [0, 0, 64, 64]))
            if cur is None:
                return "error", 0.0
            sim   = _similarity(ref, cur)
            state = "match" if sim >= self.zone.get("threshold", 0.90) else "no_match"
            return state, sim
        try:
            return self._evaluator.evaluate(capture_region)
        except Exception as e:
            log.error(f"ZoneWorker.tick: {e}")
            return "error", 0.0

    def should_fire(self, state: str) -> bool:
        """
        Returns True when zone should trigger.
        - Default (transition): fires only on no_match→match change.
        - repeat_on_cooldown=True: fires every cooldown while condition holds.
          Use this for persistent buffs that need repeated casting.
        """
        import random
        raw_cond  = self.zone.get("condition", "match")
        condition = "match" if raw_cond in ("match", "found") else "no_match"
        name      = self.zone.get("name", "?")
        repeat    = self.zone.get("repeat_on_cooldown", False)

        if state != condition:
            if self._prev != state:
                log.debug(f"Zone '{name}': state={state} != condition={condition} → no fire")
            self._prev = state
            return False

        base_cd  = self.zone.get("cooldown_ms", 500)
        human_ms = self.zone.get("humanize_ms", 0)
        jitter   = random.randint(-human_ms, human_ms) if human_ms > 0 else 0
        cooldown = max(50, base_cd + jitter) / 1000.0
        elapsed  = time.time() - self._last_fire

        if elapsed < cooldown:
            return False

        # Transition mode: only fire on state change
        if not repeat and self._prev == state:
            log.debug(f"Zone '{name}': unchanged, repeat_on_cooldown=False → skip")
            return False

        log.info(f"Zone '{name}': FIRE! state={state} repeat={repeat} elapsed={elapsed:.1f}s")
        self._prev      = state
        self._last_fire = time.time()
        # Store actual cooldown (base ± jitter) for journal display
        self.zone["_actual_cooldown_ms"] = int(cooldown * 1000)
        return True


# ── Action executor ───────────────────────────────────────────────────────────
def _fire_action(zone: dict):
    atype = zone.get("action_type", "key")
    name  = zone.get("name", "?")
    # Log to journal
    try:
        from core.journal import get_journal
        get_journal().on_monitor_trigger(
            zone.get("id", -1), name,
            zone.get("action_key","") or f"macro#{zone.get('action_macro_id','')}",
            zone.get("cooldown_ms", 0),
            actual_cooldown_ms=zone.get("_actual_cooldown_ms", 0),
        )
    except Exception as _je:
        log.debug(f"journal log: {_je}")
    try:
        if atype == "key":
            key = zone.get("action_key", "")
            if key:
                import threading as _t
                from core.macro_engine import _execute_steps
                stop = _t.Event()
                _t.Thread(
                    target=_execute_steps,
                    args=([{"key": key, "delay_ms": 0}], stop, f"Monitor:{name}"),
                    daemon=True
                ).start()
                log.debug(f"Monitor fired key '{key}' for zone '{name}'")

        elif atype == "macro":
            mid = zone.get("action_macro_id")
            if mid is not None:
                from core.macro_engine import get_engine
                eng    = get_engine()
                macro  = eng._macros.get(mid)
                if macro:
                    from core.macro_engine import MacroRunner
                    MacroRunner(macro).start()
                    log.debug(f"Monitor fired macro {mid} for zone '{name}'")
    except Exception as e:
        log.error(f"_fire_action zone '{name}': {e}")


# ── Priority queue for concurrent triggers ────────────────────────────────────
class TriggerQueue:
    """
    Queues zone triggers by priority.
    Priority 1 (critical) → executes immediately, blocks lower priorities.
    Priority 2 (normal)   → executes if no critical is pending.
    Priority 3 (background) → only if nothing else pending.
    Zones with parallel=True bypass the queue entirely.
    """
    def __init__(self):
        self._lock    = threading.Lock()
        self._pending: list[dict] = []   # sorted by priority

    def add(self, zone: dict, sim: float):
        if zone.get("parallel", False):
            _fire_action(zone)
            return
        with self._lock:
            # Avoid duplicates (same zone already queued)
            zid = zone["id"]
            if any(z["id"] == zid for z in self._pending):
                return
            self._pending.append({**zone, "_sim": sim})
            self._pending.sort(key=lambda z: z.get("priority", 2))

    def flush(self):
        """Fire the highest-priority pending action. Call once per tick."""
        with self._lock:
            if not self._pending:
                return
            # Fire only the top item; remove items of same priority that share
            # the same action (de-duplicate bursts)
            top = self._pending.pop(0)
        _fire_action(top)


# ── Capture thread ────────────────────────────────────────────────────────────
class MonitorThread(threading.Thread):
    def __init__(self, get_zones_fn, fps: int = 10):
        super().__init__(daemon=True, name="MonitorThread")
        self._get_zones  = get_zones_fn
        self._interval   = 1.0 / max(1, fps)
        self._quit       = threading.Event()
        self._workers:   dict[int, ZoneWorker] = {}
        self._queue      = TriggerQueue()

    def set_fps(self, fps: int):
        self._interval = 1.0 / max(1, fps)

    def stop(self):
        self._quit.set()

    def run(self):
        log.info("MonitorThread started")
        while not self._quit.is_set():
            t0    = time.time()
            zones = [z for z in self._get_zones() if z.get("active", False)]
            self._sync_workers(zones)

            for zone in zones:
                zid = zone["id"]
                worker = self._workers.get(zid)
                if not worker: continue
                try:
                    state, sim = worker.tick()
                    monitor_signals.zone_state.emit(zid, state)
                    if worker.should_fire(state):
                        log.info(
                            f"Zone '{zone['name']}' "
                            f"p={zone.get('priority',2)} sim={sim:.3f}")
                        monitor_signals.zone_triggered.emit(zid, zone["name"], sim)
                        self._queue.add(zone, sim)
                except Exception as e:
                    log.error(f"Zone {zid}: {e}")
                    monitor_signals.zone_state.emit(zid, "error")

            self._queue.flush()

            elapsed = time.time() - t0
            self._quit.wait(timeout=max(0.0, self._interval - elapsed))

        log.info("MonitorThread stopped")

    def _sync_workers(self, zones: list[dict]):
        ids = {z["id"] for z in zones}
        for zid in list(self._workers):
            if zid not in ids: del self._workers[zid]
        for z in zones:
            zid = z["id"]
            if zid in self._workers: self._workers[zid].update(z)
            else:                    self._workers[zid] = ZoneWorker(z)


# ── MonitorEngine singleton ───────────────────────────────────────────────────
class MonitorEngine:
    def __init__(self):
        self._thread: MonitorThread | None = None
        self._fps    = 10

    def start(self, fps: int = None):
        if fps: self._fps = fps
        if self._thread and self._thread.is_alive():
            self._thread.set_fps(self._fps); return
        from core.monitor_store import get_monitor_store
        self._thread = MonitorThread(
            get_zones_fn=get_monitor_store().active_zones,
            fps=self._fps
        )
        self._thread.start()
        monitor_signals.engine_started.emit()
        log.info(f"MonitorEngine started @ {self._fps}fps")

    def stop(self):
        if self._thread:
            self._thread.stop()
            self._thread.join(timeout=3)
            self._thread = None
        monitor_signals.engine_stopped.emit()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def switch_scene(self, sid: int):
        from core.monitor_store import get_monitor_store
        get_monitor_store().set_active_scene(sid)
        monitor_signals.scene_changed.emit(sid)
        log.info(f"Scene switched → {sid}")

    def toggle(self):
        """Start or stop monitoring — used by hotkey."""
        if self.is_running(): self.stop()
        else: self.start()

    def register_hotkey(self, hk: str):
        """
        Register a global hotkey that toggles the monitor engine.
        Hooks into pynput listener via macro_engine's HotkeyListener.
        """
        if not hk: return
        try:
            from core.macro_engine import get_engine
            eng = get_engine()
            _TOGGLE_ID = -998
            # Store toggle macro
            eng._macros[_TOGGLE_ID] = {
                "id": _TOGGLE_ID, "name": "Monitor Toggle",
                "hotkey": hk, "mode": 0,
                "steps": [], "_monitor_toggle": True,
            }
            eng._hotkey_map.setdefault(hk, [])
            if _TOGGLE_ID not in eng._hotkey_map[hk]:
                eng._hotkey_map[hk].append(_TOGGLE_ID)
            log.info(f"Monitor hotkey registered: {hk}")
        except Exception as e:
            log.error(f"register_hotkey: {e}")

    def load_hotkey_from_settings(self):
        """Called at startup to restore monitor hotkey from config."""
        try:
            from core.font_scale import _load_settings
            hk = _load_settings().get("monitor_hotkey", "")
            if hk: self.register_hotkey(hk)
        except Exception as e:
            log.error(f"load_hotkey_from_settings: {e}")


_engine: MonitorEngine | None = None
def get_monitor_engine() -> MonitorEngine:
    global _engine
    if _engine is None: _engine = MonitorEngine()
    return _engine
