"""
MacroX — Journal / Event Log
Stores macro execution events and exposes Qt signals for live updates.
"""
import time, logging
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

MAX_ENTRIES = 2000


@dataclass
class JournalEntry:
    ts:          float        # unix timestamp
    macro_id:    int
    macro_name:  str
    event:       str          # "started" | "stopped" | "step" | "error"
    detail:      str = ""
    step_key:    str = ""
    step_delay:  int = 0
    duration_ms: int = 0      # filled on "stopped"
    steps_done:  int = 0      # filled on "stopped"


class _JournalSignals(QObject):
    entry_added    = pyqtSignal(object)   # JournalEntry
    session_reset  = pyqtSignal()


class Journal:
    def __init__(self):
        self.signals  = _JournalSignals()
        self._entries: list[JournalEntry] = []
        # per-run state: macro_id → (start_ts, steps_done)
        self._runs:   dict[int, tuple[float, int]] = {}
        self._session_start: float = time.time()

    def on_macro_started(self, macro_id: int, macro_name: str):
        self._runs[macro_id] = (time.time(), 0)
        e = JournalEntry(
            ts=time.time(), macro_id=macro_id, macro_name=macro_name,
            event="started", detail=f"Макрос '{macro_name}' запущен"
        )
        self._push(e)

    def on_macro_stopped(self, macro_id: int, macro_name: str):
        run = self._runs.pop(macro_id, None)
        duration = int((time.time() - run[0]) * 1000) if run else 0
        steps_done = run[1] if run else 0
        e = JournalEntry(
            ts=time.time(), macro_id=macro_id, macro_name=macro_name,
            event="stopped",
            detail=f"Макрос '{macro_name}' завершён — {steps_done} нажатий за {duration}мс",
            duration_ms=duration, steps_done=steps_done
        )
        self._push(e)

    def on_step_executed(self, macro_id: int, macro_name: str, key: str, delay_ms: int):
        if macro_id in self._runs:
            ts, cnt = self._runs[macro_id]
            self._runs[macro_id] = (ts, cnt + 1)
        e = JournalEntry(
            ts=time.time(), macro_id=macro_id, macro_name=macro_name,
            event="step", detail=f"{key}  +{delay_ms}мс",
            step_key=key, step_delay=delay_ms
        )
        self._push(e)

    def on_error(self, macro_id: int, macro_name: str, msg: str):
        self._runs.pop(macro_id, None)
        e = JournalEntry(
            ts=time.time(), macro_id=macro_id, macro_name=macro_name,
            event="error", detail=f"Ошибка: {msg}"
        )
        self._push(e)

    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def entries_for(self, macro_id: int) -> list[JournalEntry]:
        return [e for e in self._entries if e.macro_id == macro_id]

    def clear(self):
        self._entries.clear()
        self._session_start = time.time()
        self.signals.session_reset.emit()

    def stats(self) -> dict:
        """Aggregate stats for the current session."""
        runs     = [e for e in self._entries if e.event == "stopped"]
        errors   = [e for e in self._entries if e.event == "error"]
        steps    = [e for e in self._entries if e.event == "step"]
        total_ms = sum(e.duration_ms for e in runs)
        delays   = [e.step_delay for e in steps if e.step_delay > 0]
        return {
            "runs":        len(runs),
            "errors":      len(errors),
            "steps":       len(steps),
            "total_ms":    total_ms,
            "avg_delay":   int(sum(delays) / len(delays)) if delays else 0,
            "min_delay":   min(delays) if delays else 0,
            "max_delay":   max(delays) if delays else 0,
        }

    def on_monitor_trigger(self, zone_id: int, zone_name: str, action: str,
                        cooldown_ms: int, actual_cooldown_ms: int = 0):
        e = JournalEntry(
            ts=time.time(), macro_id=zone_id, macro_name=zone_name,
            event="monitor",
            detail=(
                f"→ {action}  "
                f"(cooldown {actual_cooldown_ms or cooldown_ms}мс)"
            ),
            step_key=action, step_delay=cooldown_ms,
        )
        self._push(e)

    def _push(self, e: JournalEntry):
        self._entries.append(e)
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[: MAX_ENTRIES // 10]
        self.signals.entry_added.emit(e)
        log.debug(f"Journal: [{e.event.upper()}] {e.macro_name} — {e.detail}")


_journal: Journal | None = None

def get_journal() -> Journal:
    global _journal
    if _journal is None:
        _journal = Journal()
    return _journal

