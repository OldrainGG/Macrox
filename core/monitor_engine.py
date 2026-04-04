"""
MacroX — Monitor Engine v2

Features:
  - Priority queue: critical zones (p=1) fire before normal (p=2) before background (p=3)
  - Parallel flag per zone: bypass queue, fire immediately regardless of others
  - Scene-aware: only zones of active scene are evaluated
  - Transition detection: fires only on state CHANGE (match→no_match etc.)
  - Per-zone cooldown to prevent spam
  - Thread-safe Qt signals for UI updates
  - All action execution routed through ActionPipeline (centralized)
  - AND/OR/NOT logic via ConditionGroups (condition_engine.py)
"""
import time, threading, logging, base64
from io import BytesIO
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)


# ── Signals ───────────────────────────────────────────────────────────────────
class _MonitorSignals(QObject):
    zone_triggered  = pyqtSignal(int, str, float)   # zone_id, name, similarity
    zone_state      = pyqtSignal(int, str)           # zone_id, "match"|"no_match"|"error"
    zone_value      = pyqtSignal(int, str)           # zone_id, display_str (ocr_read only)
    engine_started  = pyqtSignal()
    engine_stopped  = pyqtSignal()
    scene_changed   = pyqtSignal(int)                # new scene_id

monitor_signals = _MonitorSignals()


# ── Image utilities ───────────────────────────────────────────────────────────
def _similarity(img_a, img_b) -> float:
    """
    Pixel-match similarity: fraction of pixels where each channel diff < tolerance.
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
    tolerance = 30
    diff  = np.abs(a - b)
    match = (diff < tolerance).all(axis=2)
    return float(match.mean())


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


# ── Action pipeline helpers ───────────────────────────────────────────────────

def _build_pipeline_action(zone: dict):
    """
    Построить Action из данных зоны/группы для отправки в ActionPipeline.
    Вызывается только когда should_fire() / group.tick() вернул True.
    """
    from core.action_pipeline import Action
    atype = zone.get("action_type", "key")
    return Action(
        priority        = zone.get("priority", 2),
        action_type     = atype,
        parallel        = zone.get("parallel", False),
        key             = zone.get("action_key", "") if atype == "key" else "",
        macro_id        = zone.get("action_macro_id") if atype == "macro" else None,
        state_var_name  = zone.get("state_var_name", "") if atype == "state" else "",
        state_var_value = zone.get("state_var_value") if atype == "state" else None,
        source          = "monitor",
        name            = zone.get("name", ""),
        zone_id         = zone.get("id", -1),
        cooldown_ms     = zone.get("_actual_cooldown_ms", zone.get("cooldown_ms", 0)),
    )


def _log_monitor_trigger(zone: dict):
    """Записать событие срабатывания зоны или группы в журнал."""
    try:
        from core.journal import get_journal
        atype = zone.get("action_type", "key")
        if atype == "key":
            action_str = zone.get("action_key", "")
        elif atype == "macro":
            action_str = f"macro#{zone.get('action_macro_id', '')}"
        elif atype == "state":
            action_str = f"state:{zone.get('state_var_name','')}={zone.get('state_var_value','')}"
        else:
            action_str = atype
        get_journal().on_monitor_trigger(
            zone_id            = zone.get("id", -1),
            zone_name          = zone.get("name", ""),
            action             = action_str,
            cooldown_ms        = zone.get("cooldown_ms", 0),
            actual_cooldown_ms = zone.get("_actual_cooldown_ms", 0),
        )
    except Exception as e:
        log.debug(f"_log_monitor_trigger: {e}")


# ── Per-zone state tracker ────────────────────────────────────────────────────
class ZoneWorker:
    """
    Delegates evaluation to ZoneEvaluator (monitor_match.py).
    Supports both pixel similarity and template matching zone types.
    Tracks _last_state for use by ConditionGroups.
    """
    def __init__(self, zone: dict):
        self.zone             = zone
        self._prev            = None
        self._last_fire       = 0.0
        self._last_state      = "no_match"   # читается GroupManager
        self._evaluator       = None
        # ocr_read tracking
        self._last_read_value = None   # последнее успешно прочитанное значение
        self._fail_streak     = 0      # подряд идущих OCR-ошибок
        self._var_warned      = False  # залогировали warning о несуществующей переменной
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
            # Fallback: plain pixel similarity
            ref_b64 = self.zone.get("reference", "")
            if not ref_b64:
                self._last_state = "error"
                return "error", 0.0
            ref = b64_to_image(ref_b64)
            if ref is None:
                self._last_state = "error"
                return "error", 0.0
            cur = capture_region(self.zone.get("rect", [0, 0, 64, 64]))
            if cur is None:
                self._last_state = "error"
                return "error", 0.0
            sim   = _similarity(ref, cur)
            state = "match" if sim >= self.zone.get("threshold", 0.90) else "no_match"
            self._last_state = state
            return state, sim

        try:
            state, sim = self._evaluator.evaluate(capture_region)
            self._last_state = state
            return state, sim
        except Exception as e:
            log.error(f"ZoneWorker.tick: {e}")
            self._last_state = "error"
            return "error", 0.0

    def should_fire(self, state: str) -> bool:
        """
        Returns True when zone should trigger.
        - Default (transition): fires only on no_match→match change.
        - repeat_on_cooldown=True: fires every cooldown while condition holds.
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

        if not repeat and self._prev == state:
            log.debug(f"Zone '{name}': unchanged, repeat_on_cooldown=False → skip")
            return False

        log.info(f"Zone '{name}': FIRE! state={state} repeat={repeat} elapsed={elapsed:.1f}s")
        self._prev      = state
        self._last_fire = time.time()
        self.zone["_actual_cooldown_ms"] = int(cooldown * 1000)
        return True


# ── Capture thread ────────────────────────────────────────────────────────────
class MonitorThread(threading.Thread):
    def __init__(self, get_zones_fn, fps: int = 10):
        super().__init__(daemon=True, name="MonitorThread")
        self._get_zones    = get_zones_fn
        self._interval     = 1.0 / max(1, fps)
        self._quit         = threading.Event()
        self._workers:     dict[int, ZoneWorker] = {}

        # Condition groups (AND/OR/NOT logic)
        from core.condition_engine import GroupManager
        self._group_manager = GroupManager()

    def set_fps(self, fps: int):
        self._interval = 1.0 / max(1, fps)

    def stop(self):
        self._quit.set()

    def run(self):
        log.info("MonitorThread started")
        # Инициализируем pipeline заранее (тёплый старт рабочего потока)
        from core.action_pipeline import get_pipeline
        from core.monitor_store   import get_monitor_store
        pipeline = get_pipeline()

        while not self._quit.is_set():
            t0    = time.time()
            zones = [z for z in self._get_zones() if z.get("active", False)]
            self._sync_workers(zones)

            # Синхронизировать группы текущей сцены
            groups = get_monitor_store().active_groups()
            self._group_manager.sync(groups)

            # ── Тик каждой зоны ──────────────────────────────────────────
            for zone in zones:
                zid    = zone["id"]
                worker = self._workers.get(zid)
                if not worker:
                    continue
                ztype = zone.get("zone_type", "pixel")
                try:
                    if ztype == "ocr_read":
                        # Polling path: no trigger, no pipeline — direct StateStore write
                        value, display = worker._evaluator.eval_ocr_read(capture_region)
                        if value is not None:
                            worker._fail_streak = 0
                            worker._last_state  = "match"   # для ConditionGroups: читает = match
                            var_name = zone.get("state_var_name", "")
                            if var_name:
                                from core.state_store import get_state_store
                                ss = get_state_store()
                                if ss.has(var_name):
                                    # Cooldown: не спамить StateStore быстрее cooldown_ms
                                    cd = max(50, zone.get("cooldown_ms", 500)) / 1000.0
                                    if time.time() - worker._last_fire >= cd:
                                        ss.set(var_name, value)
                                        worker._last_fire = time.time()
                                elif not worker._var_warned:
                                    log.warning(
                                        f"ocr_read zone '{zone['name']}': "
                                        f"state var '{var_name}' not found in StateStore"
                                    )
                                    worker._var_warned = True
                        else:
                            worker._fail_streak += 1
                            worker._last_state = "no_match"
                            fail_limit = zone.get("ocr_fail_limit", 5)
                            if worker._fail_streak == fail_limit:
                                log.error(
                                    f"Zone '{zone['name']}': OCR failed "
                                    f"{worker._fail_streak}x in a row"
                                )
                            display = "—"
                        monitor_signals.zone_state.emit(zid, worker._last_state)
                        monitor_signals.zone_value.emit(zid, display)
                    else:
                        # Existing pixel/template trigger path
                        state, sim = worker.tick()
                        monitor_signals.zone_state.emit(zid, state)
                        if worker.should_fire(state):
                            log.info(
                                f"Zone '{zone['name']}' "
                                f"p={zone.get('priority', 2)} sim={sim:.3f}"
                            )
                            monitor_signals.zone_triggered.emit(zid, zone["name"], sim)
                            _log_monitor_trigger(zone)
                            pipeline.submit(_build_pipeline_action(zone))
                except Exception as e:
                    log.error(f"Zone {zid}: {e}")
                    monitor_signals.zone_state.emit(zid, "error")

            # ── Condition groups (AND/OR/NOT) ─────────────────────────────
            # Собрать актуальные состояния всех зон из workers
            zone_states: dict[int, str] = {
                zid: w._last_state for zid, w in self._workers.items()
            }

            fired_groups = self._group_manager.evaluate_all(zone_states)
            for grp in fired_groups:
                log.info(f"ConditionGroup '{grp['name']}': FIRE!")
                monitor_signals.zone_triggered.emit(grp["id"], grp["name"], 1.0)
                _log_monitor_trigger(grp)
                pipeline.submit(_build_pipeline_action(grp))

            elapsed = time.time() - t0
            self._quit.wait(timeout=max(0.0, self._interval - elapsed))

        log.info("MonitorThread stopped")

    def _sync_workers(self, zones: list[dict]):
        ids = {z["id"] for z in zones}
        for zid in list(self._workers):
            if zid not in ids:
                del self._workers[zid]
        for z in zones:
            zid = z["id"]
            if zid in self._workers:
                self._workers[zid].update(z)
            else:
                self._workers[zid] = ZoneWorker(z)


# ── MonitorEngine singleton ───────────────────────────────────────────────────
class MonitorEngine:
    def __init__(self):
        self._thread: MonitorThread | None = None
        self._fps    = 10

    def start(self, fps: int = None):
        if fps:
            self._fps = fps
        if self._thread and self._thread.is_alive():
            self._thread.set_fps(self._fps)
            return
        # Прогреть pipeline перед запуском мониторинга
        from core.action_pipeline import get_pipeline
        get_pipeline()

        from core.monitor_store import get_monitor_store
        self._thread = MonitorThread(
            get_zones_fn=get_monitor_store().active_zones,
            fps=self._fps,
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
        if self.is_running():
            self.stop()
        else:
            self.start()

    def register_hotkey(self, hk: str):
        """Register a global hotkey that toggles the monitor engine."""
        if not hk:
            return
        try:
            from core.macro_engine import get_engine
            eng = get_engine()
            _TOGGLE_ID = -998
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
            if hk:
                self.register_hotkey(hk)
        except Exception as e:
            log.error(f"load_hotkey_from_settings: {e}")


_engine: MonitorEngine | None = None

def get_monitor_engine() -> MonitorEngine:
    global _engine
    if _engine is None:
        _engine = MonitorEngine()
    return _engine
