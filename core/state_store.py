"""
MacroX — State Store (Этап 4)

Глобальное хранилище переменных состояния игры.

Переменные:
  bool   — buff_active = True/False
  str    — mode = "idle" | "combat" | "town"  (choices задаёт допустимые значения)
  int    — hp_pct = 0–100, mana_value = 320

Персистентность:
  Схема (name, type, default, choices, description) → config/states.json
  Текущие значения (value) — только runtime, не сохраняются

Потокобезопасность:
  threading.Lock на чтение/запись value и _vars
"""

import json
import logging
import threading
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

_CONFIG_PATH = Path("config/states.json")

VAR_TYPES = ("bool", "str", "int")


class _StateSignals(QObject):
    state_changed = pyqtSignal(str, object)   # (var_name, new_value)
    vars_updated  = pyqtSignal()              # переменная добавлена/удалена


class StateStore:
    """
    Singleton. Использовать через get_state_store().

    Каждая переменная хранится как dict:
      {
        "name":        str,          # уникальный ключ
        "type":        str,          # "bool" | "str" | "int"
        "default":     ...,          # значение по умолчанию
        "choices":     list[str],    # для type="str": допустимые enum-значения
        "description": str,          # опциональное описание
        "_value":      ...,          # runtime-значение, не сохраняется
      }
    """

    def __init__(self):
        self.signals = _StateSignals()
        self._lock   = threading.Lock()
        self._vars:  dict[str, dict] = {}   # name → var dict
        self._load()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def all_vars(self) -> list[dict]:
        """Вернуть копию всех переменных (без _value в схеме — добавляем отдельно)."""
        with self._lock:
            result = []
            for v in self._vars.values():
                row = {k: val for k, val in v.items() if not k.startswith("_")}
                row["value"] = v.get("_value", v.get("default"))
                result.append(row)
            return result

    def add_var(self, name: str, var_type: str, default=None,
                choices: list | None = None, description: str = "") -> bool:
        """Добавить переменную. Возвращает False если имя уже занято."""
        name = name.strip()
        if not name or var_type not in VAR_TYPES:
            return False
        with self._lock:
            if name in self._vars:
                return False
            default = self._coerce(default, var_type, choices)
            self._vars[name] = {
                "name":        name,
                "type":        var_type,
                "default":     default,
                "choices":     choices or [],
                "description": description,
                "_value":      default,
            }
        self._save()
        self.signals.vars_updated.emit()
        log.info(f"StateStore: added var '{name}' type={var_type} default={default!r}")
        return True

    def remove_var(self, name: str) -> bool:
        with self._lock:
            if name not in self._vars:
                return False
            del self._vars[name]
        self._save()
        self.signals.vars_updated.emit()
        log.info(f"StateStore: removed var '{name}'")
        return True

    def rename_var(self, old_name: str, new_name: str) -> bool:
        """Переименовать переменную (ключ в dict и поле name)."""
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return False
        with self._lock:
            if old_name not in self._vars or new_name in self._vars:
                return False
            v = self._vars.pop(old_name)
            v["name"] = new_name
            self._vars[new_name] = v
        self._save()
        self.signals.vars_updated.emit()
        log.info(f"StateStore: renamed '{old_name}' → '{new_name}'")
        return True

    def update_var(self, name: str, **kwargs) -> bool:
        """Обновить схему переменной (не runtime-значение)."""
        with self._lock:
            if name not in self._vars:
                return False
            v = self._vars[name]
            if "type" in kwargs:
                v["type"] = kwargs["type"]
            if "default" in kwargs:
                v["default"] = self._coerce(kwargs["default"], v["type"], v["choices"])
            if "choices" in kwargs:
                v["choices"] = kwargs["choices"]
            if "description" in kwargs:
                v["description"] = kwargs["description"]
        self._save()
        self.signals.vars_updated.emit()
        return True

    # ── Runtime get/set ───────────────────────────────────────────────────────

    def get(self, name: str, fallback=None):
        """Вернуть текущее runtime-значение переменной."""
        with self._lock:
            v = self._vars.get(name)
            if v is None:
                return fallback
            return v.get("_value", v.get("default"))

    def set(self, name: str, value) -> bool:
        """
        Установить runtime-значение. Эмитирует state_changed и пишет в журнал.
        Вызывать из любого потока — безопасно.
        """
        with self._lock:
            v = self._vars.get(name)
            if v is None:
                log.warning(f"StateStore.set: unknown var '{name}'")
                return False
            old_value = v.get("_value", v.get("default"))
            new_value = self._coerce(value, v["type"], v["choices"])
            v["_value"] = new_value

        # Уведомления — за пределами lock
        if old_value != new_value:
            log.debug(f"StateStore: '{name}' {old_value!r} → {new_value!r}")
            try:
                from core.journal import get_journal
                get_journal().on_state_changed(name, old_value, new_value)
            except Exception as e:
                log.debug(f"StateStore journal: {e}")
            self.signals.state_changed.emit(name, new_value)
        return True

    def reset_all(self):
        """Сбросить все переменные к default (вызывается при старте сессии)."""
        with self._lock:
            for v in self._vars.values():
                v["_value"] = v.get("default")
        log.info("StateStore: all vars reset to default")
        self.signals.vars_updated.emit()

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._vars

    def var_type(self, name: str) -> str | None:
        with self._lock:
            v = self._vars.get(name)
            return v["type"] if v else None

    def choices(self, name: str) -> list:
        with self._lock:
            v = self._vars.get(name)
            return list(v["choices"]) if v else []

    # ── Condition evaluation ──────────────────────────────────────────────────

    def evaluate(self, condition: dict) -> bool:
        """
        Проверить условие вида:
          {"state_var": "hp_pct", "op": "<=", "value": 30}
          {"state_var": "buff_active", "op": "==", "value": True}
          {"state_var": "mode", "op": "==", "value": "combat"}

        Поддерживаемые операторы: ==, !=, >, <, >=, <=
        Для bool/str поддерживается только == и !=
        """
        name  = condition.get("state_var")
        op    = condition.get("op", "==")
        value = condition.get("value")

        if not name:
            return True

        current = self.get(name)
        if current is None:
            log.debug(f"StateStore.evaluate: var '{name}' not found → pass through")
            return True

        with self._lock:
            vtype = self._vars.get(name, {}).get("type", "str")

        try:
            target = self._coerce(value, vtype, self.choices(name))
            if   op == "==": return current == target
            elif op == "!=": return current != target
            elif op == ">":  return current >  target
            elif op == "<":  return current <  target
            elif op == ">=": return current >= target
            elif op == "<=": return current <= target
            else:
                log.warning(f"StateStore.evaluate: unknown op '{op}'")
                return True
        except Exception as e:
            log.warning(f"StateStore.evaluate: {e} → pass through")
            return True

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        try:
            if _CONFIG_PATH.exists():
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                for raw in data.get("variables", []):
                    name = raw.get("name", "").strip()
                    if not name:
                        continue
                    vtype   = raw.get("type", "str")
                    default = self._coerce(raw.get("default"), vtype, raw.get("choices", []))
                    self._vars[name] = {
                        "name":        name,
                        "type":        vtype,
                        "default":     default,
                        "choices":     raw.get("choices", []),
                        "description": raw.get("description", ""),
                        "_value":      default,
                    }
                log.info(f"StateStore: loaded {len(self._vars)} variables")
            else:
                log.info("StateStore: no config file, starting empty")
        except Exception as e:
            log.error(f"StateStore._load: {e}", exc_info=True)

    def _save(self):
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                variables = [
                    {
                        "name":        v["name"],
                        "type":        v["type"],
                        "default":     v["default"],
                        "choices":     v["choices"],
                        "description": v["description"],
                    }
                    for v in self._vars.values()
                ]
            _CONFIG_PATH.write_text(
                json.dumps({"variables": variables}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            log.error(f"StateStore._save: {e}", exc_info=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _coerce(value, vtype: str, choices: list | None = None):
        """Привести значение к нужному типу с безопасным fallback."""
        try:
            if vtype == "bool":
                if isinstance(value, str):
                    return value.lower() not in ("false", "0", "no", "")
                return bool(value) if value is not None else False
            elif vtype == "int":
                return int(value) if value is not None else 0
            else:  # str
                s = str(value) if value is not None else ""
                if choices and s not in choices and choices:
                    return choices[0]
                return s
        except Exception:
            defaults = {"bool": False, "int": 0, "str": ""}
            return defaults.get(vtype, "")


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: StateStore | None = None


def get_state_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store
