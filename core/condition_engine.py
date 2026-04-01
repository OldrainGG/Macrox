"""
MacroX — Condition Engine

Вычисляет логические выражения AND / OR / NOT над состояниями зон мониторинга.

Структура группы (хранится в monitors.json внутри сцены):
{
  "id": 1,
  "name": "Группа: флага + нет мороза",
  "expression": {
    "op": "AND",
    "operands": [
      {"zone_id": 3},
      {"op": "NOT", "operands": [{"zone_id": 5}]}
    ]
  },
  "action_type": "key",
  "action_key":  "Q",
  "action_macro_id": null,
  "cooldown_ms":  3000,
  "humanize_ms":  200,
  "priority":     2,
  "parallel":     false,
  "active":       true
}

Операнды:
  {"zone_id": N}                              — состояние одной зоны
  {"op": "AND"|"OR"|"NOT", "operands": [...]} — вложенное выражение

Состояние зоны считается True, если последний известный state == "match".
NOT принимает ровно один операнд.
"""

import logging
import time
import random
from typing import Optional

log = logging.getLogger(__name__)


# ── Expression evaluator ──────────────────────────────────────────────────────

def evaluate(expr: dict, zone_states: dict[int, str]) -> bool:
    """
    Рекурсивно вычислить логическое выражение.

    Args:
        expr:        словарь {"op": ..., "operands": [...]} или {"zone_id": N}
        zone_states: map zone_id → last known state ("match" | "no_match" | "error")

    Returns:
        True если выражение выполняется.
    """
    if "zone_id" in expr:
        zid   = expr["zone_id"]
        state = zone_states.get(zid, "no_match")
        return state == "match"

    op       = expr.get("op", "").upper()
    operands = expr.get("operands", [])

    if op == "AND":
        return all(evaluate(o, zone_states) for o in operands)
    if op == "OR":
        return any(evaluate(o, zone_states) for o in operands)
    if op == "NOT":
        if not operands:
            return True
        return not evaluate(operands[0], zone_states)

    log.warning(f"ConditionEngine: неизвестный оператор '{op}', возвращаю False")
    return False


def zone_ids_in_expr(expr: dict) -> set[int]:
    """Собрать все zone_id, задействованные в выражении."""
    ids: set[int] = set()
    if "zone_id" in expr:
        ids.add(expr["zone_id"])
    for op in expr.get("operands", []):
        ids |= zone_ids_in_expr(op)
    return ids


# ── ConditionGroup runtime tracker ───────────────────────────────────────────

class ConditionGroup:
    """
    Runtime-обёртка над одной группой.
    Хранит состояние между тиками: предыдущий результат и время последнего срабатывания.
    """

    def __init__(self, group: dict):
        self.group      = group
        self._prev      = False
        self._last_fire = 0.0

    def update(self, group: dict):
        self.group = group

    @property
    def active(self) -> bool:
        return self.group.get("active", False)

    def tick(self, zone_states: dict[int, str]) -> bool:
        """
        Вычислить выражение и вернуть True если группа должна сработать.
        Логика cooldown/transition аналогична ZoneWorker.should_fire().
        """
        expr = self.group.get("expression")
        if not expr:
            return False

        result = evaluate(expr, zone_states)

        repeat   = self.group.get("repeat_on_cooldown", False)
        base_cd  = self.group.get("cooldown_ms", 1000)
        human_ms = self.group.get("humanize_ms", 0)
        jitter   = random.randint(-human_ms, human_ms) if human_ms > 0 else 0
        cooldown = max(50, base_cd + jitter) / 1000.0
        elapsed  = time.time() - self._last_fire
        name     = self.group.get("name", "?")

        if not result:
            self._prev = False
            return False

        if elapsed < cooldown:
            return False

        if not repeat and self._prev:
            log.debug(f"Group '{name}': unchanged True, repeat=False → skip")
            return False

        log.info(f"Group '{name}': FIRE!")
        self._prev      = True
        self._last_fire = time.time()
        self.group["_actual_cooldown_ms"] = int(cooldown * 1000)
        return True


# ── GroupManager: синхронизация групп внутри MonitorThread ───────────────────

class GroupManager:
    """
    Управляет набором ConditionGroup для одной сцены.
    Вызывается из MonitorThread после получения всех zone_states.
    """

    def __init__(self):
        self._groups: dict[int, ConditionGroup] = {}   # group_id → ConditionGroup

    def sync(self, groups: list[dict]):
        """Добавить новые группы, обновить изменившиеся, удалить исчезнувшие."""
        ids = {g["id"] for g in groups}
        for gid in list(self._groups):
            if gid not in ids:
                del self._groups[gid]
        for g in groups:
            gid = g["id"]
            if gid in self._groups:
                self._groups[gid].update(g)
            else:
                self._groups[gid] = ConditionGroup(g)

    def evaluate_all(self, zone_states: dict[int, str]) -> list[dict]:
        """
        Вернуть список групп, которые должны сработать в этом тике.
        Порядок: по приоритету (меньше = важнее).
        """
        fired = []
        for cg in sorted(self._groups.values(),
                         key=lambda x: x.group.get("priority", 2)):
            if not cg.active:
                continue
            if cg.tick(zone_states):
                fired.append(cg.group)
        return fired
