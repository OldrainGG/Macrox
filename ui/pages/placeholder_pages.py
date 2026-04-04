"""
MacroX — Placeholder pages for future phases
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout
from PyQt6.QtCore import Qt
from ui.theme import COLORS, FONTS


def _make_placeholder(icon: str, title: str, description: str, phase: str) -> QWidget:
    c = COLORS
    page = QWidget()
    page.setStyleSheet(f"background-color: {c['bg_main']};")

    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # Top bar
    topbar = QWidget()
    topbar.setFixedHeight(64)
    topbar.setStyleSheet(f"background-color: {c['bg_panel']}; border-bottom: 1px solid {c['border']};")
    tb_layout = QHBoxLayout(topbar)
    tb_layout.setContentsMargins(24, 0, 24, 0)

    t = QLabel(title)
    t.setStyleSheet(f"color: {c['text_primary']}; font-size: {FONTS['size_xl']}; font-weight: 700; background: transparent;")
    tb_layout.addWidget(t)
    tb_layout.addStretch()

    badge = QLabel(phase)
    badge.setStyleSheet(f"""
        color: {c['amber']};
        background-color: {c['amber_dim']};
        border: 1px solid {c['amber']};
        border-radius: 4px;
        padding: 2px 10px;
        font-size: {FONTS['size_sm']};
        font-weight: 600;
    """)
    tb_layout.addWidget(badge)
    layout.addWidget(topbar)

    # Center content
    center = QWidget()
    center.setStyleSheet("background: transparent;")
    center_layout = QVBoxLayout(center)
    center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    center_layout.setSpacing(16)

    icon_label = QLabel(icon)
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setStyleSheet(f"font-size: 64px; color: {c['border_bright']}; background: transparent;")

    title_label = QLabel(title)
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_label.setStyleSheet(f"color: {c['text_secondary']}; font-size: {FONTS['size_xl']}; font-weight: 700; background: transparent;")

    desc_label = QLabel(description)
    desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    desc_label.setWordWrap(True)
    desc_label.setMaximumWidth(400)
    desc_label.setStyleSheet(f"color: {c['text_muted']}; font-size: {FONTS['size_md']}; background: transparent;")

    phase_label = QLabel(f"Будет добавлено в {phase}")
    phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    phase_label.setStyleSheet(f"""
        color: {c['amber']};
        background-color: {c['amber_dim']};
        border: 1px solid {c['amber_dim']};
        border-radius: 6px;
        padding: 6px 16px;
        font-size: {FONTS['size_sm']};
    """)

    center_layout.addWidget(icon_label)
    center_layout.addWidget(title_label)
    center_layout.addWidget(desc_label)
    center_layout.addSpacing(8)
    center_layout.addWidget(phase_label, 0, Qt.AlignmentFlag.AlignCenter)

    layout.addWidget(center, 1)
    return page


from ui.pages.settings_page import SettingsPage as SettingsPage  # real impl


from ui.pages.monitor_page import MonitorPage as MonitorPage  # real impl


class BlueprintPage(QWidget):
    def __new__(cls, parent=None):
        return _make_placeholder(
            "🔷", "Blueprint-редактор",
            "Визуальный редактор сценариев в стиле Unreal Engine — ноды, условия, ветвления и триггеры.",
            "Фаза 5"
        )


# LogPage is now implemented in ui/pages/log_page.py
from ui.pages.log_page import TabbedLogPage as LogPage  # re-export (tabbed)

# StatePage is now implemented in ui/pages/state_page.py
from ui.pages.state_page import StatePage as StatePage  # re-export
