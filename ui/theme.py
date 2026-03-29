"""
MacroX — Theme & Style Definitions
Dark cyberpunk-industrial aesthetic
"""

COLORS = {
    # Backgrounds
    "bg_deep":      "#0A0B0F",
    "bg_main":      "#0F1117",
    "bg_panel":     "#151820",
    "bg_card":      "#1A1E2A",
    "bg_elevated":  "#1F2433",
    "bg_hover":     "#252A3A",
    "bg_active":    "#2A3045",

    # Accent — electric blue
    "accent":       "#3D8EF0",
    "accent_bright":"#5AA3FF",
    "accent_dim":   "#1E4A8A",
    "accent_glow":  "rgba(61, 142, 240, 0.15)",

    # Secondary accent — amber
    "amber":        "#F0A030",
    "amber_dim":    "#7A5018",

    # Status colors
    "success":      "#2ECC71",
    "success_dim":  "#1A5E38",
    "warning":      "#F39C12",
    "danger":       "#E74C3C",
    "danger_dim":   "#6E2222",

    # Text
    "text_primary":   "#E8ECF4",
    "text_secondary": "#8A92A8",
    "text_muted":     "#4A5068",
    "text_accent":    "#5AA3FF",

    # Borders
    "border":       "#252A3A",
    "border_bright":"#353D55",
    "border_accent":"rgba(61, 142, 240, 0.4)",
}

FONTS = {
    "display":  "Segoe UI",
    "mono":     "Consolas",
    "ui":       "Segoe UI",
    "size_xs":  "10px",
    "size_sm":  "11px",
    "size_md":  "13px",
    "size_lg":  "15px",
    "size_xl":  "18px",
    "size_xxl": "24px",
}


def get_app_stylesheet() -> str:
    c = COLORS
    return f"""
/* ── Global ───────────────────────────────────────────── */
QWidget {{
    background-color: {c['bg_main']};
    color: {c['text_primary']};
    font-family: "{FONTS['ui']}";
    font-size: {FONTS['size_md']};
    border: none;
    outline: none;
}}

/* Explicit size overrides for common widgets so font scale works universally */
QLabel {{
    font-size: {FONTS['size_sm']};
}}
QPushButton {{
    font-size: {FONTS['size_md']};
}}
QComboBox, QLineEdit, QTextEdit, QPlainTextEdit {{
    font-size: {FONTS['size_md']};
}}
QSpinBox, QDoubleSpinBox {{
    font-size: {FONTS['size_sm']};
}}
QCheckBox {{
    font-size: {FONTS['size_sm']};
}}
QTabBar::tab {{
    font-size: {FONTS['size_sm']};
}}

QMainWindow {{
    background-color: {c['bg_deep']};
}}

/* ── Scrollbar ────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {c['bg_panel']};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {c['border_bright']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['accent']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {c['bg_panel']};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border_bright']};
    border-radius: 3px;
}}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border_bright']};
    border-radius: 6px;
    padding: 7px 16px;
    font-size: {FONTS['size_md']};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {c['bg_hover']};
    border-color: {c['accent']};
    color: {c['accent_bright']};
}}
QPushButton:pressed {{
    background-color: {c['bg_active']};
    border-color: {c['accent_bright']};
}}
QPushButton:disabled {{
    background-color: {c['bg_panel']};
    color: {c['text_muted']};
    border-color: {c['border']};
}}

/* Primary Button */
QPushButton[class="primary"] {{
    background-color: {c['accent_dim']};
    color: {c['accent_bright']};
    border-color: {c['accent']};
    font-weight: 600;
}}
QPushButton[class="primary"]:hover {{
    background-color: {c['accent']};
    color: #FFFFFF;
}}

/* Danger Button */
QPushButton[class="danger"] {{
    background-color: {c['danger_dim']};
    color: {c['danger']};
    border-color: {c['danger']};
}}
QPushButton[class="danger"]:hover {{
    background-color: {c['danger']};
    color: white;
}}

/* ── Inputs ───────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {c['bg_panel']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: {FONTS['size_md']};
    selection-background-color: {c['accent_dim']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {c['accent']};
    background-color: {c['bg_card']};
}}

/* ── SpinBox ──────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {c['bg_panel']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 5px 8px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {c['bg_elevated']};
    border: none;
    width: 18px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {c['accent_dim']};
}}

/* ── ComboBox ─────────────────────────────────────────── */
QComboBox {{
    background-color: {c['bg_panel']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 100px;
}}
QComboBox:hover {{
    border-color: {c['border_bright']};
}}
QComboBox:focus {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border_accent']};
    border-radius: 6px;
    selection-background-color: {c['accent_dim']};
    outline: none;
    padding: 2px;
}}

/* ── Slider ───────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {c['bg_elevated']};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['accent']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {c['accent_bright']};
}}
QSlider::sub-page:horizontal {{
    background: {c['accent']};
    border-radius: 2px;
}}

/* ── CheckBox ─────────────────────────────────────────── */
QCheckBox {{
    color: {c['text_secondary']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {c['border_bright']};
    background-color: {c['bg_panel']};
}}
QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}

/* ── Labels ───────────────────────────────────────────── */
QLabel {{
    color: {c['text_secondary']};
    background: transparent;
}}
QLabel[class="title"] {{
    color: {c['text_primary']};
    font-size: {FONTS['size_xl']};
    font-weight: 700;
}}
QLabel[class="subtitle"] {{
    color: {c['text_muted']};
    font-size: {FONTS['size_sm']};
}}
QLabel[class="accent"] {{
    color: {c['accent_bright']};
}}

/* ── Tooltip ──────────────────────────────────────────── */
QToolTip {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border_accent']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {FONTS['size_sm']};
}}

/* ── Frame / GroupBox ─────────────────────────────────── */
QFrame[class="card"] {{
    background-color: {c['bg_card']};
    border: 1px solid {c['border']};
    border-radius: 8px;
}}
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px;
    color: {c['text_muted']};
    font-size: {FONTS['size_sm']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {c['text_secondary']};
}}

/* ── Separator ────────────────────────────────────────── */
QFrame[frameShape="4"],
QFrame[frameShape="5"] {{
    color: {c['border']};
}}
"""
