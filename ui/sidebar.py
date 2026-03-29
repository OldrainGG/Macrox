"""
MacroX — Sidebar Navigation
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon

from ui.theme import COLORS, FONTS


class NavButton(QPushButton):
    """Single navigation item in the sidebar."""

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.icon_char = icon
        self.label_text = label
        self._active = False
        self._setup()

    def _setup(self):
        self.setFixedHeight(46)
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

    def set_active(self, active: bool):
        self._active = active
        self._update_style()

    def _update_style(self):
        c = COLORS
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c['bg_active']};
                    color: {c['accent_bright']};
                    border: none;
                    border-left: 3px solid {c['accent']};
                    border-radius: 0px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: {FONTS['size_md']};
                    font-weight: 600;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c['text_secondary']};
                    border: none;
                    border-left: 3px solid transparent;
                    border-radius: 0px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: {FONTS['size_md']};
                    font-weight: 400;
                }}
                QPushButton:hover {{
                    background-color: {c['bg_hover']};
                    color: {c['text_primary']};
                    border-left: 3px solid {c['border_bright']};
                }}
            """)
        self.setText(f"  {self.icon_char}   {self.label_text}")


class Sidebar(QWidget):
    """Left navigation panel."""

    page_changed = pyqtSignal(int)

    NAV_ITEMS = [
        ("⌨",  "Макросы"),
        ("⚙",  "Настройки"),
        ("👁",  "Мониторинг"),
        ("🔷",  "Blueprint"),
        ("📋",  "Журнал"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[NavButton] = []
        self._current = 0
        self._setup_ui()

    def _setup_ui(self):
        c = COLORS
        self.setFixedWidth(210)
        self.setStyleSheet(f"background-color: {c['bg_panel']}; border-right: 1px solid {c['border']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Logo area ──────────────────────────────────
        logo_widget = QWidget()
        logo_widget.setFixedHeight(64)
        logo_widget.setStyleSheet(f"background-color: {c['bg_deep']}; border-bottom: 1px solid {c['border']};")
        logo_layout = QHBoxLayout(logo_widget)
        logo_layout.setContentsMargins(16, 0, 16, 0)

        logo_icon = QLabel("◈")
        logo_icon.setStyleSheet(f"color: {c['accent']}; font-size: 22px; background: transparent;")

        logo_text = QLabel("MacroX")
        logo_text.setStyleSheet(f"""
            color: {c['text_primary']};
            font-size: {FONTS['size_xl']};
            font-weight: 700;
            letter-spacing: 1px;
            background: transparent;
        """)

        logo_layout.addWidget(logo_icon)
        logo_layout.addWidget(logo_text)
        logo_layout.addStretch()
        layout.addWidget(logo_widget)

        # ── Section header ─────────────────────────────
        section_label = QLabel("НАВИГАЦИЯ")
        section_label.setStyleSheet(f"""
            color: {c['text_muted']};
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 2px;
            padding: 16px 16px 6px 20px;
            background: transparent;
        """)
        layout.addWidget(section_label)

        # ── Nav buttons ────────────────────────────────
        for idx, (icon, label) in enumerate(self.NAV_ITEMS):
            btn = NavButton(icon, label)
            btn.clicked.connect(lambda checked, i=idx: self._on_click(i))
            self._buttons.append(btn)
            layout.addWidget(btn)

        # ── Spacer ─────────────────────────────────────
        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # ── Divider ────────────────────────────────────

        # Set first active
        self._set_active(0)

    def _on_click(self, index: int):
        self._set_active(index)
        self.page_changed.emit(index)

    def _set_active(self, index: int):
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == index)
        self._current = index

