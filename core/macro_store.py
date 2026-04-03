"""
MacroX — Macro storage (JSON-based).
Handles save/load of all macros to config/macros.json

Fixes:
  - add() now uses a persistent auto-increment counter instead of id(macro)
  - update() uses {**existing, **data} merge — partial updates never wipe fields
"""
import json, logging
from pathlib import Path
from core.logger import trace_calls

log = logging.getLogger(__name__)
CONFIG_DIR  = Path(__file__).parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)
MACROS_FILE = CONFIG_DIR / "macros.json"


class MacroStore:
    def __init__(self):
        self._macros:   list[dict] = []
        self._next_id:  int        = 1
        self.load()

    @trace_calls
    def load(self) -> list[dict]:
        if MACROS_FILE.exists():
            try:
                with open(MACROS_FILE, "r", encoding="utf-8") as f:
                    self._macros = json.load(f)
                # Rebuild next_id from stored ids to avoid collisions
                existing_ids = [m.get("id", 0) for m in self._macros if isinstance(m.get("id"), int)]
                self._next_id = max(existing_ids, default=0) + 1
                log.info(f"Loaded {len(self._macros)} macros from {MACROS_FILE}")
            except Exception as e:
                log.error(f"Failed to load macros: {e}")
                self._macros  = []
                self._next_id = 1
        else:
            log.info("No macros file found — starting fresh")
            self._macros  = []
            self._next_id = 1
        return self._macros

    @trace_calls
    def save(self) -> bool:
        try:
            with open(MACROS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._macros, f, ensure_ascii=False, indent=2)
            log.info(f"Saved {len(self._macros)} macros to {MACROS_FILE}")
            return True
        except Exception as e:
            log.error(f"Failed to save macros: {e}")
            return False

    @trace_calls
    def add(self, macro: dict) -> int:
        """Add macro with a stable auto-increment id (never uses id(obj))."""
        macro = dict(macro)
        macro["id"] = self._next_id
        self._next_id += 1
        self._macros.append(macro)
        self.save()
        return macro["id"]

    @trace_calls
    def update(self, macro_id: int, data: dict) -> bool:
        """Merge-update: only fields present in data are changed, rest preserved."""
        for i, m in enumerate(self._macros):
            if m.get("id") == macro_id:
                self._macros[i] = {**m, **data, "id": macro_id}
                self.save()
                return True
        log.warning(f"Macro id={macro_id} not found for update")
        return False

    @trace_calls
    def delete(self, macro_id: int) -> bool:
        before = len(self._macros)
        self._macros = [m for m in self._macros if m.get("id") != macro_id]
        if len(self._macros) < before:
            self.save(); return True
        log.warning(f"Macro id={macro_id} not found for delete")
        return False

    def get(self, macro_id: int) -> dict | None:
        for m in self._macros:
            if m.get("id") == macro_id:
                return dict(m)
        return None

    def all(self) -> list[dict]:
        return list(self._macros)


# Singleton
_store: MacroStore | None = None

def get_store() -> MacroStore:
    global _store
    if _store is None:
        _store = MacroStore()
    return _store
