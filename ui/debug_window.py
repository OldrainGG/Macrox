"""
MacroX — Debug Window
- On open: replays full session buffer (all events since app start)
- Level filters: actually hide/show lines by re-rendering
- Stays connected to bridge for new events
- Search bar: partial-match highlight + prev/next navigation
"""
import os, logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QCheckBox, QFileDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QColor, QTextCharFormat, QTextDocument
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

# Цвета подсветки поиска
SEARCH_HIGHLIGHT_BG  = "#3A5A2A"   # фон всех совпадений
SEARCH_HIGHLIGHT_FG  = "#C8F0A0"   # текст всех совпадений
SEARCH_CURRENT_BG    = "#7A5A00"   # фон текущего совпадения
SEARCH_CURRENT_FG    = "#FFE566"   # текст текущего совпадения


class DebugWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused  = False

        # Search state
        self._search_selections: list = []   # все QTextEdit.ExtraSelection
        self._search_current    = -1         # индекс текущего выделения
        self._search_query      = ""

        # Debounce таймер — чтобы не перестраивать при каждом символе
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)   # мс после последнего ввода
        self._search_timer.timeout.connect(self._do_search)

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

        # ── Search bar ────────────────────────────────────
        sb_w = QWidget(); sb_w.setFixedHeight(36)
        sb_w.setStyleSheet(
            f"background:{c['bg_panel']};"
            f"border-bottom:1px solid {c['border']};"
        )
        sb_lay = QHBoxLayout(sb_w)
        sb_lay.setContentsMargins(12, 4, 12, 4)
        sb_lay.setSpacing(6)

        search_icon = QLabel("🔍")
        search_icon.setStyleSheet(f"background:transparent;font-size:12px;")
        sb_lay.addWidget(search_icon)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск в логах... (частичное совпадение)")
        self.search_edit.setFixedHeight(24)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {c['bg_elevated']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 4px;
                padding: 0 8px;
                font-family: {FONTS['mono']};
                font-size: {FONTS['size_sm']};
            }}
            QLineEdit:focus {{
                border-color: {c['accent_bright']};
            }}
        """)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._search_next)
        sb_lay.addWidget(self.search_edit, 1)

        # Счётчик совпадений
        self.search_cnt_lbl = QLabel("")
        self.search_cnt_lbl.setFixedWidth(80)
        self.search_cnt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.search_cnt_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-family:{FONTS['ui']};"
            f"font-size:{FONTS['size_xs']};background:transparent;"
        )
        sb_lay.addWidget(self.search_cnt_lbl)

        # Навигация ↑ ↓
        for label, slot in [("↑", self._search_prev), ("↓", self._search_next)]:
            btn = QPushButton(label)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(self._btn_s())
            btn.clicked.connect(slot)
            sb_lay.addWidget(btn)

        # Кнопка закрыть поиск
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(self._btn_s())
        close_btn.clicked.connect(self._clear_search)
        sb_lay.addWidget(close_btn)

        lay.addWidget(sb_w)

        # ── Log text area ─────────────────────────────────
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_edit.setStyleSheet(
            f"QTextEdit{{background:{c['bg_deep']};color:{c['text_secondary']};"
            f"border:none;padding:6px;font-family:{FONTS['mono']};font-size:{FONTS['size_sm']};}}")
        lay.addWidget(self.log_edit, 1)

        # ── Status bar ────────────────────────────────────
        stb_w = QWidget(); stb_w.setFixedHeight(26)
        stb_w.setStyleSheet(f"background:{c['bg_panel']};border-top:1px solid {c['border']};")
        stb = QHBoxLayout(stb_w); stb.setContentsMargins(12,0,12,0)
        self.status_lbl = QLabel("...")
        self.status_lbl.setStyleSheet(f"color:{c['text_muted']};font-family:{FONTS['ui']};"
                                       f"font-size:{FONTS['size_xs']};")
        stb.addWidget(self.status_lbl); stb.addStretch()
        from core.logger import LOG_DIR, LOG_FILE
        self._log_file = LOG_FILE
        ob = QPushButton(f"Открыть папку логов  ({LOG_FILE.name})")
        ob.setFixedHeight(20)
        ob.setStyleSheet(f"background:transparent;color:{c['accent_dim']};border:none;"
                         f"font-size:{FONTS['size_xs']};font-family:{FONTS['ui']};")
        ob.clicked.connect(lambda: os.startfile(str(LOG_DIR)))
        stb.addWidget(ob)
        lay.addWidget(stb_w)

    # ── Search logic ──────────────────────────────────────────────────────────

    def _on_search_text_changed(self, text: str):
        """Запускает debounce-таймер — поиск выполнится через 120мс после последнего символа."""
        self._search_query = text
        self._search_timer.start()

    def _do_search(self):
        """Построить список всех совпадений и подсветить их."""
        query = self._search_query.strip()
        self._search_selections = []
        self._search_current    = -1

        if not query:
            self.log_edit.setExtraSelections([])
            self.search_cnt_lbl.setText("")
            self._update_search_indicator()
            return

        doc    = self.log_edit.document()
        cursor = QTextCursor(doc)

        # Формат для всех совпадений (фоновая подсветка)
        fmt_all = QTextCharFormat()
        fmt_all.setBackground(QColor(SEARCH_HIGHLIGHT_BG))
        fmt_all.setForeground(QColor(SEARCH_HIGHLIGHT_FG))

        flags = QTextDocument.FindFlag(0)   # case-insensitive по умолчанию

        while True:
            cursor = doc.find(query, cursor, flags)
            if cursor.isNull():
                break
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format  = fmt_all
            self._search_selections.append(sel)

        total = len(self._search_selections)
        if total == 0:
            self.log_edit.setExtraSelections([])
            self.search_cnt_lbl.setText("0 совпад.")
            self.search_edit.setStyleSheet(self._search_edit_style(no_match=True))
            return

        self.search_edit.setStyleSheet(self._search_edit_style(no_match=False))

        # Перейти к первому совпадению
        self._search_current = 0
        self._apply_search_selections()
        self._scroll_to_current()

    def _search_next(self):
        if not self._search_selections:
            return
        self._search_current = (self._search_current + 1) % len(self._search_selections)
        self._apply_search_selections()
        self._scroll_to_current()

    def _search_prev(self):
        if not self._search_selections:
            return
        self._search_current = (self._search_current - 1) % len(self._search_selections)
        self._apply_search_selections()
        self._scroll_to_current()

    def _apply_search_selections(self):
        """Перекрасить текущее совпадение в accent-цвет, остальные — в фоновый."""
        fmt_all = QTextCharFormat()
        fmt_all.setBackground(QColor(SEARCH_HIGHLIGHT_BG))
        fmt_all.setForeground(QColor(SEARCH_HIGHLIGHT_FG))

        fmt_cur = QTextCharFormat()
        fmt_cur.setBackground(QColor(SEARCH_CURRENT_BG))
        fmt_cur.setForeground(QColor(SEARCH_CURRENT_FG))
        fmt_cur.setFontWeight(700)

        for i, sel in enumerate(self._search_selections):
            sel.format = fmt_cur if i == self._search_current else fmt_all

        self.log_edit.setExtraSelections(self._search_selections)
        self._update_search_indicator()

    def _scroll_to_current(self):
        if 0 <= self._search_current < len(self._search_selections):
            cur = self._search_selections[self._search_current].cursor
            self.log_edit.setTextCursor(cur)
            self.log_edit.ensureCursorVisible()

    def _update_search_indicator(self):
        total = len(self._search_selections)
        if total == 0:
            self.search_cnt_lbl.setText("")
            return
        idx = self._search_current + 1
        self.search_cnt_lbl.setText(f"{idx} / {total}")

    def _clear_search(self):
        self.search_edit.clear()
        self.log_edit.setExtraSelections([])
        self._search_selections = []
        self._search_current    = -1
        self.search_cnt_lbl.setText("")

    def _search_edit_style(self, no_match: bool = False) -> str:
        c = COLORS
        border = "#C0392B" if no_match else c['accent_bright']
        bg     = "#3A1515" if no_match else c['bg_elevated']
        return f"""
            QLineEdit {{
                background: {bg};
                color: {c['text_primary']};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 0 8px;
                font-family: {FONTS['mono']};
                font-size: {FONTS['size_sm']};
            }}
            QLineEdit:focus {{
                border-color: {border};
            }}
        """

    # ── Live new entry ────────────────────────────────────────────────────────
    def _on_new_entry(self, levelname: str, message: str):
        if self._paused: return
        self._append_line(levelname, message)
        # Обновить поиск если активен
        if self._search_query.strip():
            self._search_timer.start()

    # ── Append one line (respects current filter) ─────────────────────────────
    def _append_line(self, levelname: str, message: str):
        cb = self._cbs.get(levelname)
        if cb and not cb.isChecked():
            return
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
        self.log_edit.clear()
        from core.logger import get_session_buffer
        for levelname, message in get_session_buffer():
            self._append_line(levelname, message)
        # Переприменить поиск после перерисовки
        if self._search_query.strip():
            self._do_search()

    def _clear(self):
        self.log_edit.clear()
        self.cnt_lbl.setText("0 строк")
        self._clear_search()

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
