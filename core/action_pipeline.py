"""
MacroX — Centralized Action Pipeline

Единая точка выполнения всех действий приложения.

Источники:
  • MonitorEngine  — зоны-триггеры → нажатие клавиши или запуск макроса
  • MacroEngine    — (будущее: условные макросы)
  • Blueprint      — (будущее: ноды)

Гарантии:
  • Сортировка по приоритету: p=1 (critical) → p=2 (normal) → p=3 (background)
  • parallel=True  → немедленный запуск в собственном потоке (минуя очередь)
  • parallel=False → строгая сериализация через рабочий поток
  • Все нажатия клавиш идут через _execute_steps → DirectInput (совместимо с играми)
"""

import threading
import logging
from dataclasses import dataclass, field
from queue import PriorityQueue, Empty
from typing import Optional

log = logging.getLogger(__name__)


@dataclass(order=True)
class Action:
    """
    Дескриптор действия для pipeline.

    Поля сортировки (PriorityQueue):
      priority  — меньше = важнее (1 critical, 2 normal, 3 background)
      seq       — порядковый номер; меньше = раньше поступил (FIFO внутри одного приоритета)

    Все остальные поля исключены из сравнения.
    """
    priority: int = field(default=2)
    seq:      int = field(default=0, repr=False)   # Заполняется pipeline при submit

    # Тип действия
    action_type: str = field(compare=False, default="key")
    # "key"   → нажать одну клавишу (поле key)
    # "steps" → выполнить список шагов (поле steps)
    # "macro" → запустить макрос через MacroEngine (поле macro_id)

    parallel: bool = field(compare=False, default=False)

    # Payload
    key:      str            = field(compare=False, default="")
    steps:    list           = field(compare=False, default_factory=list)
    macro_id: Optional[int]  = field(compare=False, default=None)

    # Метаданные (для логирования)
    source:      str = field(compare=False, default="unknown")  # "monitor" | "macro" | "blueprint"
    name:        str = field(compare=False, default="")          # читаемое имя зоны/макроса
    zone_id:     int = field(compare=False, default=-1)
    cooldown_ms: int = field(compare=False, default=0)


class ActionPipeline:
    """
    Singleton. Использовать через get_pipeline().

    Архитектура:
      submit(action)
        ├── parallel=True  → Thread(daemon).start()  → _execute()   [немедленно]
        └── parallel=False → PriorityQueue           → WorkerThread → _execute() [сериализованно]
    """

    def __init__(self):
        self._queue    = PriorityQueue()
        self._seq      = 0
        self._seq_lock = threading.Lock()
        self._running  = True
        self._worker   = threading.Thread(
            target=self._worker_loop, daemon=True, name="PipelineWorker"
        )
        self._worker.start()
        log.info("ActionPipeline started")

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, action: Action):
        """Поставить действие в очередь или запустить немедленно. Thread-safe."""
        if action.parallel:
            threading.Thread(
                target=self._execute,
                args=(action,),
                daemon=True,
                name=f"Pipeline-{action.name or action.source}",
            ).start()
            log.debug(f"Pipeline: parallel {action.action_type} from '{action.source}'")
        else:
            with self._seq_lock:
                self._seq += 1
                action.seq = self._seq
            self._queue.put(action)
            log.debug(
                f"Pipeline: enqueued p={action.priority} seq={action.seq} "
                f"{action.action_type} from '{action.source}' "
                f"(qsize≈{self._queue.qsize()})"
            )

    def stop(self):
        """Остановить рабочий поток. Вызывать при завершении приложения."""
        self._running = False
        self._worker.join(timeout=2)
        log.info("ActionPipeline stopped")

    # ── Worker ────────────────────────────────────────────────────────────────

    def _worker_loop(self):
        log.debug("PipelineWorker: running")
        while self._running:
            try:
                action = self._queue.get(timeout=0.3)
            except Empty:
                continue
            try:
                self._execute(action)
            except Exception as e:
                log.error(f"PipelineWorker: {e}", exc_info=True)
            finally:
                self._queue.task_done()
        log.debug("PipelineWorker: stopped")

    # ── Execution ─────────────────────────────────────────────────────────────

    def _execute(self, action: Action):
        """Выполнить одно действие. Вызывается из worker или параллельного потока."""
        log.info(
            f"Pipeline execute: type={action.action_type} source={action.source} "
            f"name='{action.name}' parallel={action.parallel}"
        )
        try:
            if action.action_type == "key":
                self._exec_key(action.key, action.name)
            elif action.action_type == "steps":
                self._exec_steps(action.steps, action.name)
            elif action.action_type == "macro":
                self._exec_macro(action.macro_id, action.name)
            else:
                log.warning(f"Pipeline: неизвестный action_type='{action.action_type}'")
        except Exception as e:
            log.error(f"Pipeline._execute: {e}", exc_info=True)

    @staticmethod
    def _exec_key(key: str, name: str):
        """Нажать одну клавишу через _execute_steps (DirectInput-совместимо)."""
        if not key:
            return
        try:
            from core.macro_engine import _execute_steps
            stop = threading.Event()
            _execute_steps([{"key": key, "delay_ms": 0}], stop, f"Pipeline:{name}")
            log.debug(f"Pipeline: key='{key}' pressed for '{name}'")
        except Exception as e:
            log.error(f"Pipeline._exec_key '{key}': {e}")

    @staticmethod
    def _exec_steps(steps: list, name: str):
        """Выполнить список шагов макроса."""
        if not steps:
            return
        try:
            from core.macro_engine import _execute_steps
            stop = threading.Event()
            _execute_steps(steps, stop, name)
        except Exception as e:
            log.error(f"Pipeline._exec_steps '{name}': {e}")

    @staticmethod
    def _exec_macro(macro_id: Optional[int], name: str):
        """Запустить макрос через MacroEngine (создаёт MacroRunner в отдельном потоке)."""
        if macro_id is None:
            return
        try:
            from core.macro_engine import get_engine, MacroRunner
            macro = get_engine()._macros.get(macro_id)
            if macro:
                MacroRunner(macro).start()
                log.debug(f"Pipeline: macro id={macro_id} launched for '{name}'")
            else:
                log.warning(f"Pipeline: macro id={macro_id} не найден в движке")
        except Exception as e:
            log.error(f"Pipeline._exec_macro {macro_id}: {e}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: Optional[ActionPipeline] = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> ActionPipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = ActionPipeline()
    return _pipeline