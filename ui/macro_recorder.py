"""
MacroX — Macro Recorder Dialog
- Dynamic ms-field width
- "+" separators between chips
- Drag-and-drop reordering (chip moves WITH its delay)
"""
import sys, logging, time, threading
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QSpinBox, QComboBox,
    QLayout, QSizePolicy, QApplication
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QRect, QPoint, QSize,
    QMimeData, QByteArray
)
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor, QCursor
from ui.theme import COLORS, FONTS
from core.logger import trace_calls

log = logging.getLogger(__name__)

MODE_LABELS = ["Однократно", "Удержание (повтор)", "Переключение (Switch)"]
MODE_HINTS  = [
    "Макрос выполнится один раз при нажатии кнопки запуска",
    "Макрос повторяется пока удерживается кнопка запуска",
    "Первое нажатие запускает, второе — останавливает",
]

# ── Flow Layout ───────────────────────────────────────────────────────────────
class FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing=4, v_spacing=6):
        super().__init__(parent)
        self._items     = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item):           self._items.append(item)
    def count(self):                   return len(self._items)
    def itemAt(self, i):               return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i):               return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self):     return Qt.Orientation(0)
    def hasHeightForWidth(self):       return True
    def heightForWidth(self, w):       return self._layout(QRect(0,0,w,0), test=True)
    def setGeometry(self, r):          super().setGeometry(r); self._layout(r, test=False)
    def sizeHint(self):                return self.minimumSize()
    def minimumSize(self):
        s = QSize()
        for it in self._items: s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left()+m.right(), m.top()+m.bottom())

    def _layout(self, rect, test):
        m  = self.contentsMargins()
        x  = rect.x() + m.left()
        y  = rect.y() + m.top()
        rh = 0
        lw = rect.width() - m.left() - m.right()
        for it in self._items:
            sh = it.sizeHint()
            iw, ih = sh.width(), sh.height()
            if x + iw > rect.x() + m.left() + lw and x > rect.x() + m.left():
                x = rect.x() + m.left(); y += rh + self._v_spacing; rh = 0
            if not test: it.setGeometry(QRect(QPoint(x,y), sh))
            x += iw + self._h_spacing; rh = max(rh, ih)
        return y + rh - rect.y() + m.bottom()


# ── Data model ────────────────────────────────────────────────────────────────
class MacroStep:
    def __init__(self, key: str, delay_ms: int):
        self.key = key; self.delay_ms = max(0, delay_ms)
    def to_dict(self):      return {"key": self.key, "delay_ms": self.delay_ms}
    @staticmethod
    def from_dict(d):       return MacroStep(d["key"], d.get("delay_ms", 0))


# ── Step chip ─────────────────────────────────────────────────────────────────
MIME_TYPE = "application/x-macrox-chip"

class StepChip(QWidget):
    deleted      = pyqtSignal(object)
    drag_started = pyqtSignal(object)   # emits self

    def __init__(self, step: MacroStep, parent=None):
        super().__init__(parent)
        self.step = step
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._drag_start: QPoint | None = None
        self._build()

    # ── visual ────────────────────────────────────────────────────────────────
    def _build(self):
        c = COLORS
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        # drag handle
        handle = QLabel("⠿")
        handle.setFixedSize(14, 32)
        handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        handle.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        handle.setStyleSheet(
            f"color:{c['text_muted']};background:transparent;border:none;"
            f"font-size:14px;"
        )
        lay.addWidget(handle)

        # key badge — dynamic width
        key_text = self.step.key
        char_w   = max(28, min(130, len(key_text) * 9 + 14))
        kl = QLabel(key_text)
        kl.setFixedHeight(32)
        kl.setFixedWidth(char_w)
        kl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kl.setStyleSheet(
            f"background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:5px;"
            f"padding:0 4px;font-family:{FONTS['mono']};"
            f"font-size:{FONTS['size_sm']};font-weight:700;"
        )
        lay.addWidget(kl)

        # delay spinbox — dynamic width based on value digits
        sp = QSpinBox()
        sp.setRange(0, 99999)
        sp.setValue(self.step.delay_ms)
        sp.setFixedHeight(32)
        sp.setToolTip("Задержка перед нажатием (мс)")
        self._update_spin_width(sp, self.step.delay_ms)
        sp.valueChanged.connect(lambda v, s=sp: (
            setattr(self.step, 'delay_ms', v),
            self._update_spin_width(s, v)
        ))
        sp.setStyleSheet(
            f"QSpinBox{{background:{c['bg_panel']};color:{c['accent_bright']};"
            f"border:1px solid {c['border']};border-radius:4px;"
            f"padding:1px 2px;font-size:{FONTS['size_xs']};}}"
            f"QSpinBox:focus{{border-color:{c['accent']};}}"
            f"QSpinBox::up-button,QSpinBox::down-button{{"
            f"width:12px;background:{c['bg_elevated']};border:none;}}"
        )
        lay.addWidget(sp)

        ms = QLabel("мс")
        ms.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
            f"background:transparent;border:none;"
        )
        lay.addWidget(ms)

        # ✕ delete — always visible red
        db = QPushButton("✕")
        db.setFixedSize(22, 22)
        db.setToolTip("Удалить этот шаг")
        db.setStyleSheet(
            f"QPushButton{{background:{c['danger_dim']};color:{c['danger']};"
            f"border:1px solid {c['danger']};font-size:10px;font-weight:700;"
            f"border-radius:4px;padding:0;}}"
            f"QPushButton:hover{{background:{c['danger']};color:white;}}"
        )
        db.clicked.connect(lambda: self.deleted.emit(self))
        lay.addWidget(db)

    @staticmethod
    def _update_spin_width(sp: QSpinBox, val: int):
        digits = len(str(val))
        # 1-2 digits → 44px, 3 → 52, 4 → 60, 5 → 68
        w = 44 + max(0, digits - 2) * 8
        sp.setFixedWidth(w)

    # ── drag support ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._drag_start is not None and
                e.buttons() & Qt.MouseButton.LeftButton):
            dist = (e.position().toPoint() - self._drag_start).manhattanLength()
            if dist >= QApplication.startDragDistance():
                self._do_drag()
        super().mouseMoveEvent(e)

    def _do_drag(self):
        self._drag_start = None
        drag = QDrag(self)
        mime = QMimeData()
        # encode chip identity as its id()
        mime.setData(MIME_TYPE, QByteArray(str(id(self)).encode()))
        drag.setMimeData(mime)

        # ghost pixmap
        pm = QPixmap(self.size())
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setOpacity(0.7)
        self.render(p)
        p.end()
        drag.setPixmap(pm)
        drag.setHotSpot(self.rect().center())

        self.drag_started.emit(self)
        drag.exec(Qt.DropAction.MoveAction)


# ── "+" separator label ───────────────────────────────────────────────────────
class PlusSep(QWidget):
    """Thin '+' separator shown between chips."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lbl = QLabel("+")
        lbl.setFixedSize(16, 32)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};background:transparent;"
            f"border:none;font-size:{FONTS['size_md']};font-weight:700;"
        )
        lay.addWidget(lbl)


# ── Drop-aware chips container ────────────────────────────────────────────────
class ChipsContainer(QWidget):
    """
    Holds chips + separators in a FlowLayout.
    Accepts drops and reorders accordingly.
    """
    order_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._flow = FlowLayout(self, h_spacing=0, v_spacing=6)
        self._flow.setContentsMargins(10,10,10,10)
        self.setLayout(self._flow)
        self.setAcceptDrops(True)
        self._chips: list[StepChip] = []   # ordered list
        self._dragging: StepChip | None = None

    # ── public API ────────────────────────────────────────────────────────────
    def add_chip(self, chip: StepChip):
        chip.drag_started.connect(self._on_drag_start)
        self._chips.append(chip)
        self._rebuild()

    def remove_chip(self, chip: StepChip):
        if chip in self._chips:
            self._chips.remove(chip)
        self._rebuild()

    def clear_chips(self):
        self._chips.clear()
        self._rebuild()

    def chips(self) -> list[StepChip]:
        return list(self._chips)

    # ── rebuild flow from _chips list ─────────────────────────────────────────
    def _rebuild(self):
        # Remove all items from layout
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)   # type: ignore

        for i, chip in enumerate(self._chips):
            if i > 0:
                sep = PlusSep()
                self._flow.addWidget(sep)
            chip.setParent(self)
            chip.show()
            self._flow.addWidget(chip)

        self.adjustSize()
        self.update()

    # ── drag/drop ─────────────────────────────────────────────────────────────
    def _on_drag_start(self, chip: StepChip):
        self._dragging = chip

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_TYPE):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME_TYPE):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME_TYPE):
            return
        if self._dragging is None:
            return

        src_chip = self._dragging
        self._dragging = None

        if src_chip not in self._chips:
            return

        # Find drop position: which chip is closest to drop point
        drop_x = e.position().toPoint().x()
        drop_y = e.position().toPoint().y()

        target_idx = len(self._chips) - 1   # default: end
        for i, chip in enumerate(self._chips):
            cx = chip.pos().x() + chip.width() // 2
            cy = chip.pos().y() + chip.height() // 2
            # simple: find chip whose centre is closest
            if drop_y <= cy + chip.height() // 2:
                target_idx = i
                break

        src_idx = self._chips.index(src_chip)
        if src_idx == target_idx:
            e.acceptProposedAction()
            return

        self._chips.pop(src_idx)
        insert_at = target_idx if target_idx <= src_idx else target_idx - 0
        self._chips.insert(insert_at, src_chip)

        self._rebuild()
        self.order_changed.emit()
        log.debug(f"Chip reordered: {src_idx} → {insert_at}")
        e.acceptProposedAction()


# ── pynput recorder thread ────────────────────────────────────────────────────
class _RecSignals(QObject):
    step  = pyqtSignal(str, int)
    error = pyqtSignal(str)
    done  = pyqtSignal()


class _RecThread(threading.Thread):
    def __init__(self, sig: _RecSignals):
        super().__init__(daemon=True, name="MacroRecThread")
        self.sig        = sig
        self._quit_flag = threading.Event()
        self._last_t    = None
        self._held_mods: set[str] = set()

    def quit(self):
        self._quit_flag.set()

    def run(self):
        log.debug("RecThread.run() started")
        try:
            import pynput as _pt
            log.info("pynput OK")
        except ImportError:
            msg = f"pynput не установлен. Выполните: {sys.executable} -m pip install pynput"
            log.error(msg); self.sig.error.emit(msg); self.sig.done.emit(); return

        try:
            from pynput import keyboard, mouse as pmouse
            from ui._pynput_compat import build_mouse_map
            MOUSE_MAP = build_mouse_map()

            self._last_t = time.time()

            MOD_MAP: dict = {
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

            def _key_name(key) -> str:
                try:
                    return key.char.upper() if (hasattr(key,'char') and key.char) else key.name.upper()
                except Exception:
                    return str(key).upper().strip("'<>")

            def on_press(key):
                if self._quit_flag.is_set(): return False
                if key in MOD_MAP:
                    self._held_mods.add(MOD_MAP[key]); return
                now   = time.time()
                delay = int((now - self._last_t) * 1000)
                self._last_t = now
                base  = _key_name(key)
                mods  = sorted(self._held_mods)
                combo = "+".join(mods + [base]) if mods else base
                log.debug(f"Key: {combo}  {delay}ms")
                self.sig.step.emit(combo, delay)

            def on_release(key):
                MOD_MAP and self._held_mods.discard(MOD_MAP.get(key, ""))

            def on_mouse(x, y, button, pressed):
                if not pressed or self._quit_flag.is_set(): return
                now   = time.time()
                delay = int((now - self._last_t) * 1000)
                self._last_t = now
                name  = MOUSE_MAP.get(button, f"Mouse_{button.name}")
                log.debug(f"Mouse: {name}  {delay}ms")
                self.sig.step.emit(name, delay)

            kb = keyboard.Listener(on_press=on_press, on_release=on_release)
            ms = pmouse.Listener(on_click=on_mouse)
            kb.start(); ms.start()
            log.info("Listeners started — recording")
            self._quit_flag.wait()
            kb.stop(); ms.stop()
            kb.join(timeout=2); ms.join(timeout=2)
            log.info("Listeners stopped")

        except Exception as ex:
            log.error(f"RecThread: {ex}", exc_info=True)
            self.sig.error.emit(str(ex))

        self.sig.done.emit()


# ── Dialog ────────────────────────────────────────────────────────────────────
class MacroRecorderDialog(QDialog):
    recording_done = pyqtSignal(list, int)

    def __init__(self, existing_steps=None, parent=None):
        super().__init__(parent)
        self._steps: list[MacroStep] = []
        self._recording = False
        self._thread: _RecThread | None = None
        self._sig = _RecSignals()
        self._sig.step.connect(self._on_step)
        self._sig.done.connect(self._on_done)
        self._sig.error.connect(self._on_error)
        self._elapsed = 0

        if existing_steps:
            self._steps = [MacroStep.from_dict(s) for s in existing_steps]

        self._build_ui()
        for s in self._steps:
            self._add_step(s)

    def _build_ui(self):
        c = COLORS
        self.setWindowTitle("Редактор макрокода")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(True)
        self.resize(860, 580)
        self.setMinimumSize(660, 500)
        self.setStyleSheet(
            f"QDialog{{background:{c['bg_panel']};}} "
            f"QLabel{{background:transparent;border:none;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20,16,20,16); root.setSpacing(10)

        # Header
        hr = QHBoxLayout()
        t = QLabel("Макрокод")
        t.setStyleSheet(f"color:{c['text_primary']};font-size:{FONTS['size_xl']};font-weight:700;")
        hr.addWidget(t); hr.addStretch()
        hr.addWidget(QLabel("Режим:"))
        self.mode = QComboBox()
        self.mode.addItems(MODE_LABELS)
        self.mode.setFixedHeight(30); self.mode.setMinimumWidth(230)
        self.mode.setStyleSheet(
            f"QComboBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:5px;"
            f"padding:2px 8px;font-size:{FONTS['size_sm']};}}"
            f"QComboBox:hover{{border-color:{c['accent']};}}"
            f"QComboBox QAbstractItemView{{background:{c['bg_elevated']};"
            f"color:{c['text_primary']};border:1px solid {c['accent']};"
            f"selection-background-color:{c['accent_dim']};outline:none;padding:2px;}}"
        )
        self.mode.currentIndexChanged.connect(lambda i: self.mode_hint.setText(MODE_HINTS[i]))
        hr.addWidget(self.mode)
        root.addLayout(hr)

        self.mode_hint = QLabel(MODE_HINTS[0])
        self.mode_hint.setStyleSheet(f"color:{c['accent_bright']};font-size:{FONTS['size_xs']};")
        root.addWidget(self.mode_hint)

        self.instr = QLabel(
            "Нажмите «⏺ Начать запись» и вводите клавиши/кнопки мыши. "
            "Сочетания (Ctrl+, Shift+…) распознаются автоматически. "
            "Перетаскивайте элементы для изменения порядка."
        )
        self.instr.setWordWrap(True)
        self.instr.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_sm']};")
        root.addWidget(self.instr)

        self.err_lbl = QLabel("")
        self.err_lbl.setWordWrap(True)
        self.err_lbl.setStyleSheet(
            f"color:{c['danger']};font-size:{FONTS['size_sm']};"
            f"background:{c['danger_dim']};border-radius:4px;padding:4px 8px;"
        )
        self.err_lbl.hide()
        root.addWidget(self.err_lbl)

        # Chips area
        area = QFrame()
        area.setStyleSheet(
            f"background:{c['bg_deep']};border:1px solid {c['border']};border-radius:8px;"
        )
        area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        al = QVBoxLayout(area); al.setContentsMargins(0,0,0,0)

        self.empty_lbl = QLabel("Нажатия появятся здесь во время записи...")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_sm']};")
        al.addWidget(self.empty_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("background:transparent;border:none;")

        self.container = ChipsContainer()
        self.container.order_changed.connect(self._sync_steps_from_chips)
        self.scroll.setWidget(self.container)
        self.scroll.hide()
        al.addWidget(self.scroll)
        root.addWidget(area, 1)

        # Record bar
        rec = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{c['text_muted']};font-size:13px;")
        rec.addWidget(self.dot)
        self.elapsed_lbl = QLabel("")
        self.elapsed_lbl.setFixedWidth(54)
        self.elapsed_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_sm']};")
        rec.addWidget(self.elapsed_lbl)
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        rec.addWidget(self.count_lbl)
        rec.addStretch()

        self.btn_clear = QPushButton("🗑  Очистить всё")
        self.btn_clear.setFixedHeight(32)
        self.btn_clear.setStyleSheet(self._s(c['danger_dim'],c['danger'],c['danger']))
        self.btn_clear.clicked.connect(self._clear_all)
        rec.addWidget(self.btn_clear)

        self.btn_rec = QPushButton("⏺  Начать запись")
        self.btn_rec.setFixedHeight(32); self.btn_rec.setCheckable(True)
        self.btn_rec.setStyleSheet(self._rec_s(False))
        self.btn_rec.clicked.connect(self._toggle)
        rec.addWidget(self.btn_rec)
        root.addLayout(rec)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(100)
        self._ui_timer.timeout.connect(lambda: (
            setattr(self, '_elapsed', self._elapsed + 100),
            self.elapsed_lbl.setText(f"{self._elapsed/1000:.1f}с")
        ))

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{c['border']};max-height:1px;border:none;")
        root.addWidget(sep)

        br = QHBoxLayout(); br.setSpacing(8)
        btn_cancel = QPushButton("✕  Отмена")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(self._s(c['bg_elevated'],c['text_secondary'],c['border_bright']))
        btn_cancel.clicked.connect(self._do_cancel)
        self.btn_ok = QPushButton("💾  Сохранить макрокод")
        self.btn_ok.setFixedHeight(36); self.btn_ok.setEnabled(False)
        self.btn_ok.setStyleSheet(self._s(c['accent_dim'],c['accent_bright'],c['accent']))
        self.btn_ok.clicked.connect(self._confirm)
        br.addStretch(); br.addWidget(btn_cancel); br.addWidget(self.btn_ok)
        root.addLayout(br)

    # ── Record ────────────────────────────────────────────────────────────────
    @trace_calls
    def _toggle(self, *_):
        if self.btn_rec.isChecked(): self._start()
        else:                        self._stop_rec()

    @trace_calls
    def _start(self):
        self._recording = True; self._elapsed = 0
        self.err_lbl.hide()
        c = COLORS
        self.btn_rec.setText("⏹  Остановить запись")
        self.btn_rec.setStyleSheet(self._rec_s(True))
        self.dot.setStyleSheet(f"color:{c['danger']};font-size:13px;")
        self.instr.setText(
            "⏺ Идёт запись — нажимайте клавиши и кнопки мыши. "
            "Нажмите «Остановить запись» когда закончите."
        )
        self._ui_timer.start()
        self._thread = _RecThread(self._sig)
        self._thread.start()

    @trace_calls
    def _stop_rec(self):
        self._recording = False
        self._ui_timer.stop()
        if self._thread: self._thread.quit(); self._thread = None
        c = COLORS
        self.btn_rec.setText("⏺  Начать запись"); self.btn_rec.setChecked(False)
        self.btn_rec.setStyleSheet(self._rec_s(False))
        self.dot.setStyleSheet(f"color:{c['text_muted']};font-size:13px;")
        self.elapsed_lbl.setText("")
        self.instr.setText("Запись завершена. Задержки можно отредактировать. Перетащите для перестановки.")
        log.info(f"Recording stopped. Steps: {len(self._steps)}")

    def _on_step(self, key, delay):
        s = MacroStep(key, delay)
        self._steps.append(s)
        self._add_step(s)

    def _on_done(self):
        if self._recording: self._stop_rec()

    def _on_error(self, msg):
        self.err_lbl.setText(f"⚠  {msg}"); self.err_lbl.show()
        if self._recording: self._stop_rec()

    # ── Chips management ──────────────────────────────────────────────────────
    def _add_step(self, step: MacroStep):
        self.empty_lbl.hide(); self.scroll.show()
        chip = StepChip(step)
        chip.deleted.connect(self._remove_chip)
        self.container.add_chip(chip)
        self._upd_count()
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))
        self.btn_ok.setEnabled(True)

    def _remove_chip(self, chip: StepChip):
        if chip.step in self._steps: self._steps.remove(chip.step)
        self.container.remove_chip(chip)
        chip.deleteLater()
        if not self.container.chips():
            self.empty_lbl.show(); self.scroll.hide(); self.btn_ok.setEnabled(False)
        self._upd_count()

    def _clear_all(self, *_):
        self._steps.clear()
        self.container.clear_chips()
        self.empty_lbl.show(); self.scroll.hide()
        self.btn_ok.setEnabled(False); self._upd_count()

    def _sync_steps_from_chips(self):
        """After drag reorder, sync self._steps to match chip order."""
        self._steps = [chip.step for chip in self.container.chips()]
        log.debug(f"Steps resynced after reorder: {[s.key for s in self._steps]}")

    def _upd_count(self):
        n = len(self.container.chips())
        self.count_lbl.setText(f"{n} нажатий" if n else "")

    # ── Confirm / Cancel ──────────────────────────────────────────────────────
    @trace_calls
    def _confirm(self, *_):
        if self._recording: self._stop_rec()
        self._sync_steps_from_chips()
        result = [s.to_dict() for s in self._steps]
        mode   = self.mode.currentIndex()
        log.info(f"Macro saved: {len(result)} steps, mode={MODE_LABELS[mode]}")
        self.recording_done.emit(result, mode)
        QDialog.accept(self)

    def _do_cancel(self, *_):
        if self._recording: self._stop_rec()
        QDialog.reject(self)

    def get_steps(self):    return [s.to_dict() for s in self._steps]
    def get_mode(self):     return self.mode.currentIndex()

    # ── Styles ────────────────────────────────────────────────────────────────
    def _s(self, bg, fg, border):
        c = COLORS
        return (
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {border};"
            f"border-radius:6px;font-size:{FONTS['size_sm']};font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};}}"
            f"QPushButton:disabled{{background:{c['bg_elevated']};color:{c['text_muted']};"
            f"border-color:{c['border']};}}"
        )

    def _rec_s(self, active):
        c = COLORS
        if active:
            return (
                f"QPushButton{{background:{c['danger_dim']};color:{c['danger']};"
                f"border:2px solid {c['danger']};border-radius:6px;"
                f"font-size:{FONTS['size_sm']};font-weight:700;padding:0 14px;}}"
                f"QPushButton:hover{{background:{c['danger']};color:white;}}"
            )
        return (
            f"QPushButton{{background:{c['success_dim']};color:{c['success']};"
            f"border:1px solid {c['success']};border-radius:6px;"
            f"font-size:{FONTS['size_sm']};font-weight:600;padding:0 14px;}}"
            f"QPushButton:hover{{background:{c['success']};color:white;}}"
        )
