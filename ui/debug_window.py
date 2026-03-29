"""
MacroX — Debug Window
- On open: replays full session buffer (all events since app start)
- Level filters: actually hide/show lines by re-rendering
- Stays connected to bridge for new events
"""
import os, logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QCheckBox, QFileDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QColor
from ui.theme import COLORS, FONTS

log = logging.getLogger(__name__)

LEVEL_COLORS = {
    "DEBUG":    "#5A7A9A",
    "INFO":     "#6AB4F8",
    "WARNING":  "#F0A030",
    "ERROR":    "#E74C3C",
    "CRITICAL": "#FF2040",
}
LEVELS_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DebugWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused  = False
        self._build_ui()

        # Replay full session history first
        from core.logger import get_session_buffer, get_bridge
        for levelname, message in get_session_buffer():
            self._append_line(levelname, message)

        # Then connect for live updates
        get_bridge().new_entry.connect(self._on_new_entry)
        log.info("Debug window opened")

    def _build_ui(self):
        c = COLORS
        self.setWindowTitle("MacroX — Debug Console")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(880, 520)
        self.setMinimumSize(500, 300)
        self.setStyleSheet(f"QWidget{{background:{c['bg_deep']};color:{c['text_primary']};"
                           f"font-family:{FONTS['mono']};font-size:{FONTS['size_sm']};}}")

        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────
        tb_w = QWidget(); tb_w.setFixedHeight(44)
        tb_w.setStyleSheet(f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        tb = QHBoxLayout(tb_w); tb.setContentsMargins(12,0,12,0); tb.setSpacing(8)

        title = QLabel("◈ Debug Console")
        title.setStyleSheet(f"color:{c['accent_bright']};font-family:{FONTS['ui']};"
                            f"font-size:{FONTS['size_md']};font-weight:700;")
        tb.addWidget(title)

        self.cnt_lbl = QLabel("0 записей")
        self.cnt_lbl.setStyleSheet(f"color:{c['text_muted']};font-family:{FONTS['ui']};"
                                    f"font-size:{FONTS['size_sm']};")
        tb.addWidget(self.cnt_lbl)
        tb.addStretch()

        # Level filter checkboxes — toggling calls _refilter()
        self._cbs: dict[str, QCheckBox] = {}
        for lvl in ("DEBUG","INFO","WARNING","ERROR"):
            cb = QCheckBox(lvl); cb.setChecked(True)
            cb.setStyleSheet(f"""
                QCheckBox{{color:{LEVEL_COLORS[lvl]};font-family:{FONTS['ui']};
                    font-size:{FONTS['size_xs']};spacing:4px;background:transparent;}}
                QCheckBox::indicator{{width:13px;height:13px;border-radius:3px;
                    border:1px solid {c['border_bright']};background:{c['bg_panel']};}}
                QCheckBox::indicator:checked{{background:{LEVEL_COLORS[lvl]};
                    border-color:{LEVEL_COLORS[lvl]};}}
            """)
            cb.stateChanged.connect(self._refilter)
            self._cbs[lvl] = cb
            tb.addWidget(cb)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{c['border']};"); tb.addWidget(sep)

        self.btn_pause = QPushButton("⏸ Пауза")
        self.btn_pause.setCheckable(True); self.btn_pause.setFixedHeight(28)
        self.btn_pause.setStyleSheet(self._btn_s())
        self.btn_pause.toggled.connect(lambda v: setattr(self, '_paused', v))
        tb.addWidget(self.btn_pause)

        for label, slot in [("✕ Очистить", self._clear), ("💾 Сохранить", self._save)]:
            b = QPushButton(label); b.setFixedHeight(28)
            b.setStyleSheet(self._btn_s()); b.clicked.connect(slot); tb.addWidget(b)

        lay.addWidget(tb_w)

        # ── Log text area ─────────────────────────────────
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_edit.setStyleSheet(
            f"QTextEdit{{background:{c['bg_deep']};color:{c['text_secondary']};"
            f"border:none;padding:6px;font-family:{FONTS['mono']};font-size:{FONTS['size_sm']};}}")
        lay.addWidget(self.log_edit, 1)

        # ── Status bar ────────────────────────────────────
        sb_w = QWidget(); sb_w.setFixedHeight(26)
        sb_w.setStyleSheet(f"background:{c['bg_panel']};border-top:1px solid {c['border']};")
        sb = QHBoxLayout(sb_w); sb.setContentsMargins(12,0,12,0)
        self.status_lbl = QLabel("...")
        self.status_lbl.setStyleSheet(f"color:{c['text_muted']};font-family:{FONTS['ui']};"
                                       f"font-size:{FONTS['size_xs']};")
        sb.addWidget(self.status_lbl); sb.addStretch()
        from core.logger import LOG_DIR, LOG_FILE
        self._log_file = LOG_FILE
        ob = QPushButton(f"Открыть папку логов  ({LOG_FILE.name})")
        ob.setFixedHeight(20)
        ob.setStyleSheet(f"background:transparent;color:{c['accent_dim']};border:none;"
                         f"font-size:{FONTS['size_xs']};font-family:{FONTS['ui']};")
        ob.clicked.connect(lambda: os.startfile(str(LOG_DIR)))
        sb.addWidget(ob)
        lay.addWidget(sb_w)

    # ── Live new entry ────────────────────────────────────────────────────────
    def _on_new_entry(self, levelname: str, message: str):
        if self._paused: return
        self._append_line(levelname, message)

    # ── Append one line (respects current filter) ─────────────────────────────
    def _append_line(self, levelname: str, message: str):
        # Check filter
        cb = self._cbs.get(levelname)
        if cb and not cb.isChecked():
            return   # filtered out — don't add at all
        # Also filter CRITICAL under ERROR checkbox
        if levelname == "CRITICAL":
            cb_err = self._cbs.get("ERROR")
            if cb_err and not cb_err.isChecked(): return

        color = LEVEL_COLORS.get(levelname, COLORS["text_secondary"])
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = self.log_edit.currentCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

        count = self.log_edit.document().blockCount()
        self.cnt_lbl.setText(f"{count} строк")
        self.status_lbl.setText(message[:110])

    # ── Re-render on filter change ────────────────────────────────────────────
    def _refilter(self):
        """Redraws the log from session buffer applying current filters."""
        self.log_edit.clear()
        from core.logger import get_session_buffer
        for levelname, message in get_session_buffer():
            self._append_line(levelname, message)

    def _clear(self):
        self.log_edit.clear()
        self.cnt_lbl.setText("0 строк")

    def _save(self):
        from core.logger import LOG_DIR
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лог", str(LOG_DIR / "export.txt"), "Text (*.txt);;All (*)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_edit.toPlainText())
            log.info(f"Log exported: {path}")

    def closeEvent(self, e):
        try:
            from core.logger import get_bridge
            get_bridge().new_entry.disconnect(self._on_new_entry)
        except Exception:
            pass
        log.info("Debug window closed")
        e.accept()

    def _btn_s(self):
        c = COLORS
        return (f"QPushButton{{background:{c['bg_elevated']};color:{c['text_secondary']};"
                f"border:1px solid {c['border']};border-radius:4px;padding:0 10px;"
                f"font-family:{FONTS['ui']};font-size:{FONTS['size_xs']};}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}"
                f"QPushButton:checked{{background:{COLORS['amber_dim']};color:{COLORS['amber']};"
                f"border-color:{COLORS['amber']};}}")
