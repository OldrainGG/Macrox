"""
MacroX — Hotkey Capture Dialog
Single-capture. pynput mouse thread uses _quit_flag (not _stop).
"""
import logging, threading, time
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QKeyEvent, QKeySequence
from ui.theme import COLORS, FONTS

log = logging.getLogger(__name__)

MOUSE_NAMES = {
    Qt.MouseButton.LeftButton:    "Mouse1",
    Qt.MouseButton.RightButton:   "Mouse2",
    Qt.MouseButton.MiddleButton:  "Mouse3",
    Qt.MouseButton.BackButton:    "Mouse4",
    Qt.MouseButton.ForwardButton: "Mouse5",
    Qt.MouseButton.ExtraButton1:  "Mouse6",
    Qt.MouseButton.ExtraButton2:  "Mouse7",
}
SKIP_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
             Qt.Key.Key_Meta, Qt.Key.Key_unknown}


class _MouseSignals(QObject):
    clicked = pyqtSignal(str)


class _MouseListenerThread(threading.Thread):
    """Uses _quit_flag to avoid collision with Thread._stop internal method."""
    def __init__(self, signals: _MouseSignals):
        super().__init__(daemon=True)
        self.signals   = signals
        self._quit_flag = threading.Event()   # NOT _stop !

    def quit(self):
        self._quit_flag.set()

    def run(self):
        try:
            from pynput import mouse as pmouse
            from ui._pynput_compat import build_mouse_map
            BTN = build_mouse_map()
            def on_click(x, y, button, pressed):
                if not pressed or self._quit_flag.is_set():
                    return False
                name = BTN.get(button, f"Mouse_{button.name}")
                self.signals.clicked.emit(name)
                return False   # stop listener after first click

            with pmouse.Listener(on_click=on_click) as lst:
                self._quit_flag.wait()   # block until quit() called
                lst.stop()
        except Exception as e:
            log.warning(f"MouseListener: {e}")


class HotkeyCaptureDialog(QDialog):
    hotkey_captured = pyqtSignal(str)

    def __init__(self, current_hotkey: str = "", parent=None):
        super().__init__(parent)
        self._captured  = ""
        self._listening = True
        self._countdown = 15
        self._ml_thread: _MouseListenerThread | None = None
        self._ml_sig    = _MouseSignals()
        self._ml_sig.clicked.connect(self._on_mouse)
        self._setup_ui(current_hotkey)
        self._cd_timer = QTimer(self)
        self._cd_timer.setInterval(1000)
        self._cd_timer.timeout.connect(self._tick)
        self._cd_timer.start()
        self._start_ml()
        self.setFocus()

    def _start_ml(self):
        self._ml_thread = _MouseListenerThread(self._ml_sig)
        self._ml_thread.start()
        log.debug("Mouse listener started")

    def _stop_ml(self):
        if self._ml_thread:
            self._ml_thread.quit()
            self._ml_thread = None

    def _on_mouse(self, name: str):
        if self._listening:
            self._set_captured(name)

    def _setup_ui(self, current):
        c = COLORS
        self.setWindowTitle("Назначить горячую клавишу")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setModal(True)
        self.setFixedSize(440, 330)
        self.setStyleSheet(f"QDialog{{background:{c['bg_panel']};}} QLabel{{background:transparent;border:none;}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(10)

        t = QLabel("Назначить горячую клавишу")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"color:{c['text_primary']};font-size:{FONTS['size_lg']};font-weight:700;")
        lay.addWidget(t)

        self.hint = QLabel("Нажмите любую клавишу клавиатуры или кнопку мыши")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_sm']};")
        lay.addWidget(self.hint)

        self.box = QLabel("...")
        self.box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.box.setFixedHeight(64)
        self.box.setStyleSheet(self._box_style(False))
        lay.addWidget(self.box)

        if current:
            cl = QLabel(f"Текущая: {current}")
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
            lay.addWidget(cl)

        self.cd_lbl = QLabel(f"Ожидание нажатия... автоотмена через {self._countdown}с")
        self.cd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cd_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        lay.addWidget(self.cd_lbl)

        lay.addStretch()

        row = QHBoxLayout(); row.setSpacing(8)

        self.btn_retry = QPushButton("↺  Повторить")
        self.btn_retry.setFixedHeight(36)
        self.btn_retry.setEnabled(False)
        self.btn_retry.setStyleSheet(self._s(COLORS['bg_elevated'], COLORS['text_secondary'], COLORS['border_bright']))
        self.btn_retry.clicked.connect(self._retry)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(self._s(COLORS['bg_elevated'], COLORS['text_secondary'], COLORS['border_bright']))
        btn_cancel.clicked.connect(self._do_cancel)

        self.btn_ok = QPushButton("✓  Назначить")
        self.btn_ok.setFixedHeight(36)
        self.btn_ok.setEnabled(False)
        self.btn_ok.setStyleSheet(self._s(COLORS['accent_dim'], COLORS['accent_bright'], COLORS['accent']))
        self.btn_ok.clicked.connect(self._confirm)

        row.addWidget(self.btn_retry); row.addStretch()
        row.addWidget(btn_cancel); row.addWidget(self.btn_ok)
        lay.addLayout(row)

    def _tick(self):
        if not self._listening:
            self._cd_timer.stop(); return
        self._countdown -= 1
        if self._countdown <= 0:
            self._cleanup(); QDialog.reject(self)
        else:
            self.cd_lbl.setText(f"Ожидание нажатия... автоотмена через {self._countdown}с")

    def keyPressEvent(self, e: QKeyEvent):
        if not self._listening:
            super().keyPressEvent(e); return
        k = e.key()
        if k in SKIP_KEYS: return
        parts = []
        m = e.modifiers()
        if m & Qt.KeyboardModifier.ControlModifier: parts.append("Ctrl")
        if m & Qt.KeyboardModifier.ShiftModifier:   parts.append("Shift")
        if m & Qt.KeyboardModifier.AltModifier:     parts.append("Alt")
        ks = QKeySequence(k).toString()
        parts.append(ks if ks else f"Key_{k}")
        self._set_captured("+".join(parts))

    def mousePressEvent(self, e):
        if not self._listening:
            super().mousePressEvent(e); return
        btn = e.button()
        if btn == Qt.MouseButton.LeftButton and e.position().y() > self.height() - 56:
            super().mousePressEvent(e); return
        name = MOUSE_NAMES.get(btn, f"MouseBtn_{btn.value}")
        self._set_captured(name)

    def _set_captured(self, key: str):
        if not self._listening: return
        self._captured  = key
        self._listening = False
        self._cd_timer.stop()
        self._stop_ml()
        self.box.setText(key)
        self.box.setStyleSheet(self._box_style(True))
        self.hint.setText("✓ Клавиша захвачена — нажмите «Назначить»")
        self.cd_lbl.setText("Нажмите «↺ Повторить» если хотите выбрать другую")
        self.btn_ok.setEnabled(True)
        self.btn_retry.setEnabled(True)
        log.debug(f"Hotkey captured: {key}")

    def _retry(self):
        self._captured = ""; self._listening = True; self._countdown = 15
        self.box.setText("..."); self.box.setStyleSheet(self._box_style(False))
        self.hint.setText("Нажмите любую клавишу клавиатуры или кнопку мыши")
        self.cd_lbl.setText(f"Ожидание нажатия... автоотмена через {self._countdown}с")
        self.btn_ok.setEnabled(False); self.btn_retry.setEnabled(False)
        self._start_ml()
        self._cd_timer.start()

    def _confirm(self):
        self._cleanup()
        self.hotkey_captured.emit(self._captured)
        log.info(f"Hotkey assigned: {self._captured}")
        QDialog.accept(self)

    def _do_cancel(self):
        self._cleanup(); QDialog.reject(self)

    def _cleanup(self):
        self._cd_timer.stop(); self._stop_ml()

    def closeEvent(self, e):
        self._cleanup(); e.accept()

    def get_hotkey(self): return self._captured

    def _box_style(self, done: bool):
        c = COLORS
        col = c['success'] if done else c['accent_bright']
        brd = c['success'] if done else c['accent']
        return (f"background:{c['bg_deep']};color:{col};border:2px solid {brd};"
                f"border-radius:8px;font-size:24px;font-weight:700;font-family:{FONTS['mono']};")

    def _s(self, bg, fg, border):
        c = COLORS
        return (f"QPushButton{{background:{bg};color:{fg};border:1px solid {border};"
                f"border-radius:6px;font-size:{FONTS['size_sm']};font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}"
                f"QPushButton:disabled{{background:{c['bg_elevated']};color:{c['text_muted']};"
                f"border-color:{c['border']};}}")
