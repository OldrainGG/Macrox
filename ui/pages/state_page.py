"""
MacroX — State Page (Этап 4)

Страница управления переменными состояния (StateStore).
Таблица переменных с live-обновлением текущих значений.
"""

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QDialog, QLineEdit, QComboBox,
    QCheckBox, QSpinBox, QFormLayout, QDialogButtonBox,
    QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import COLORS, FONTS

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cb_style() -> str:
    c = COLORS
    return (f"QComboBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:4px;"
            f"padding:3px 8px;font-size:{FONTS['size_sm']};}}"
            f"QComboBox QAbstractItemView{{background:{c['bg_elevated']};"
            f"color:{c['text_primary']};border:1px solid {c['accent']};"
            f"selection-background-color:{c['accent_dim']};}}")

def _input_style() -> str:
    c = COLORS
    return (f"QLineEdit{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:4px;"
            f"padding:4px 8px;font-size:{FONTS['size_sm']};}}"
            f"QLineEdit:focus{{border-color:{c['accent']};}}")

def _btn_style(color: str = None) -> str:
    c = COLORS
    col = color or c['accent']
    return (f"QPushButton{{background:{col};color:{c['text_primary']};"
            f"border:none;border-radius:4px;padding:5px 14px;"
            f"font-size:{FONTS['size_sm']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent_bright']};}}"
            f"QPushButton:pressed{{background:{c['accent_dim']};}}")

def _type_badge(vtype: str) -> str:
    return {"bool": "BOOL", "str": "STR", "int": "INT"}.get(vtype, vtype.upper())

def _type_color(vtype: str) -> str:
    return {"bool": COLORS["amber"], "str": COLORS["accent_bright"],
            "int": COLORS["success"]}.get(vtype, COLORS["text_muted"])

def _fmt_value(value, vtype: str) -> str:
    if vtype == "bool":
        return "✓ True" if value else "✗ False"
    return str(value) if value is not None else "—"


# ── Variable row widget ───────────────────────────────────────────────────────

class VarRow(QFrame):
    """One row in the variable table."""

    def __init__(self, var: dict, on_delete, on_edit, parent=None):
        super().__init__(parent)
        self._var = var
        self._on_delete = on_delete
        self._on_edit   = on_edit
        self._val_lbl: QLabel | None = None
        self._build()

    def _build(self):
        c = COLORS
        self.setStyleSheet(
            f"QFrame{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:6px;}} QFrame:hover{{border-color:{c['border_bright']};}}")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0); lay.setSpacing(10)

        # Type badge
        vtype = self._var.get("type", "str")
        badge = QLabel(_type_badge(vtype))
        badge.setFixedWidth(38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color:{_type_color(vtype)};background:{c['bg_deep']};"
            f"border:1px solid {_type_color(vtype)};border-radius:3px;"
            f"font-size:{FONTS['size_xs']};font-weight:700;padding:1px 4px;")
        lay.addWidget(badge)

        # Name
        name_lbl = QLabel(self._var.get("name", ""))
        name_lbl.setFixedWidth(160)
        name_lbl.setStyleSheet(
            f"color:{c['accent_bright']};font-size:{FONTS['size_sm']};"
            f"font-weight:600;background:transparent;")
        lay.addWidget(name_lbl)

        # Description
        desc = self._var.get("description", "")
        desc_lbl = QLabel(desc or "—")
        desc_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        desc_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(desc_lbl, 1)

        # Default
        def_lbl = QLabel(f"default: {self._var.get('default', '—')}")
        def_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        def_lbl.setFixedWidth(100)
        lay.addWidget(def_lbl)

        # Current value — updated live
        self._val_lbl = QLabel(_fmt_value(self._var.get("value"), vtype))
        self._val_lbl.setFixedWidth(110)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val_lbl.setStyleSheet(
            f"color:{c['success']};font-size:{FONTS['size_sm']};"
            f"font-weight:600;background:transparent;font-family:{FONTS['mono']};")
        lay.addWidget(self._val_lbl)

        # Edit / Delete buttons
        btn_edit = QPushButton("✎")
        btn_edit.setFixedSize(28, 28)
        btn_edit.setToolTip("Редактировать")
        btn_edit.setStyleSheet(
            f"QPushButton{{background:{c['bg_elevated']};color:{c['text_secondary']};"
            f"border:1px solid {c['border']};border-radius:4px;font-size:13px;}}"
            f"QPushButton:hover{{background:{c['bg_hover']};color:{c['accent_bright']};"
            f"border-color:{c['accent']};}}")
        btn_edit.clicked.connect(lambda: self._on_edit(self._var["name"]))
        lay.addWidget(btn_edit)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(28, 28)
        btn_del.setToolTip("Удалить")
        btn_del.setStyleSheet(
            f"QPushButton{{background:{c['bg_elevated']};color:{c['text_muted']};"
            f"border:1px solid {c['border']};border-radius:4px;font-size:11px;}}"
            f"QPushButton:hover{{background:{c['danger']};color:white;border-color:{c['danger']};}}")
        btn_del.clicked.connect(lambda: self._on_delete(self._var["name"]))
        lay.addWidget(btn_del)

    def update_value(self, value):
        if self._val_lbl:
            vtype = self._var.get("type", "str")
            self._val_lbl.setText(_fmt_value(value, vtype))


# ── Add/Edit dialog ───────────────────────────────────────────────────────────

class VarDialog(QDialog):
    """Dialog for creating or editing a state variable."""

    def __init__(self, existing: dict | None = None, parent=None):
        super().__init__(parent)
        self._existing = existing
        self._result: dict | None = None
        self._build()
        if existing:
            self._load(existing)

    def _build(self):
        c = COLORS
        self.setWindowTitle("Редактировать переменную" if self._existing else "Добавить переменную")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"background:{c['bg_panel']};color:{c['text_primary']};")

        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(20, 16, 20, 16)

        form = QFormLayout(); form.setSpacing(10)

        lbl_style = f"color:{c['text_secondary']};font-size:{FONTS['size_sm']};"

        # Name
        self._name_e = QLineEdit()
        self._name_e.setPlaceholderText("hp_pct, buff_active, mode …")
        self._name_e.setStyleSheet(_input_style())
        self._original_name = self._existing["name"] if self._existing else None
        name_lbl = QLabel("Имя переменной:"); name_lbl.setStyleSheet(lbl_style)
        form.addRow(name_lbl, self._name_e)

        # Type
        self._type_cb = QComboBox()
        self._type_cb.addItem("bool  — True/False", "bool")
        self._type_cb.addItem("str   — строка/enum", "str")
        self._type_cb.addItem("int   — целое число", "int")
        self._type_cb.setStyleSheet(_cb_style())
        self._type_cb.currentIndexChanged.connect(self._on_type_change)
        type_lbl = QLabel("Тип:"); type_lbl.setStyleSheet(lbl_style)
        form.addRow(type_lbl, self._type_cb)

        # Description
        self._desc_e = QLineEdit()
        self._desc_e.setPlaceholderText("Опциональное описание")
        self._desc_e.setStyleSheet(_input_style())
        desc_lbl = QLabel("Описание:"); desc_lbl.setStyleSheet(lbl_style)
        form.addRow(desc_lbl, self._desc_e)

        lay.addLayout(form)

        # Default value section (changes with type)
        self._default_frame = QWidget()
        self._default_frame.setStyleSheet("background:transparent;")
        self._df_lay = QVBoxLayout(self._default_frame)
        self._df_lay.setContentsMargins(0, 0, 0, 0); self._df_lay.setSpacing(8)

        def_lbl = QLabel("Значение по умолчанию:")
        def_lbl.setStyleSheet(lbl_style)
        self._df_lay.addWidget(def_lbl)

        # bool default
        self._bool_cb = QComboBox()
        self._bool_cb.addItem("False", False)
        self._bool_cb.addItem("True", True)
        self._bool_cb.setStyleSheet(_cb_style())
        self._df_lay.addWidget(self._bool_cb)

        # int default
        self._int_spin = QSpinBox()
        self._int_spin.setRange(-999999, 999999)
        self._int_spin.setStyleSheet(
            f"QSpinBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:4px;padding:3px 8px;"
            f"font-size:{FONTS['size_sm']};}}")
        self._df_lay.addWidget(self._int_spin)

        # str default + choices
        self._str_frame = QWidget(); self._str_frame.setStyleSheet("background:transparent;")
        sf_lay = QVBoxLayout(self._str_frame); sf_lay.setContentsMargins(0,0,0,0); sf_lay.setSpacing(6)
        self._str_default_e = QLineEdit()
        self._str_default_e.setPlaceholderText("idle")
        self._str_default_e.setStyleSheet(_input_style())
        sf_lay.addWidget(self._str_default_e)
        ch_lbl = QLabel("Допустимые значения (через запятую, для enum):")
        ch_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        self._choices_e = QLineEdit()
        self._choices_e.setPlaceholderText("idle, combat, town")
        self._choices_e.setStyleSheet(_input_style())
        sf_lay.addWidget(ch_lbl); sf_lay.addWidget(self._choices_e)
        self._df_lay.addWidget(self._str_frame)

        lay.addWidget(self._default_frame)

        # Current value section (only shown when editing existing variable)
        self._current_frame = QWidget()
        self._current_frame.setStyleSheet("background:transparent;")
        cf_lay = QVBoxLayout(self._current_frame)
        cf_lay.setContentsMargins(0, 0, 0, 0); cf_lay.setSpacing(8)

        cur_hdr = QLabel("Текущее значение (runtime):")
        cur_hdr.setStyleSheet(lbl_style)
        cf_lay.addWidget(cur_hdr)

        self._cur_bool_cb = QComboBox()
        self._cur_bool_cb.addItem("False", False)
        self._cur_bool_cb.addItem("True", True)
        self._cur_bool_cb.setStyleSheet(_cb_style())
        cf_lay.addWidget(self._cur_bool_cb)

        self._cur_int_spin = QSpinBox()
        self._cur_int_spin.setRange(-999999, 999999)
        self._cur_int_spin.setStyleSheet(
            f"QSpinBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:4px;padding:3px 8px;"
            f"font-size:{FONTS['size_sm']};}}")
        cf_lay.addWidget(self._cur_int_spin)

        self._cur_str_e = QLineEdit()
        self._cur_str_e.setStyleSheet(_input_style())
        cf_lay.addWidget(self._cur_str_e)

        self._current_frame.setVisible(bool(self._existing))
        lay.addWidget(self._current_frame)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.setStyleSheet(
            f"QPushButton{{background:{c['accent']};color:white;border:none;"
            f"border-radius:4px;padding:5px 18px;font-size:{FONTS['size_sm']};}}"
            f"QPushButton:hover{{background:{c['accent_bright']};}}")
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._on_type_change(0)

    def _on_type_change(self, _=None):
        vtype = self._type_cb.currentData()
        self._bool_cb.setVisible(vtype == "bool")
        self._int_spin.setVisible(vtype == "int")
        self._str_frame.setVisible(vtype == "str")
        # current value widgets (only when editing)
        if self._existing:
            self._cur_bool_cb.setVisible(vtype == "bool")
            self._cur_int_spin.setVisible(vtype == "int")
            self._cur_str_e.setVisible(vtype == "str")

    def _load(self, v: dict):
        self._name_e.setText(v.get("name", ""))
        self._desc_e.setText(v.get("description", ""))
        vtype = v.get("type", "str")
        idx = self._type_cb.findData(vtype)
        if idx >= 0:
            self._type_cb.setCurrentIndex(idx)
        self._on_type_change()
        default = v.get("default")
        current = v.get("value", default)
        if vtype == "bool":
            self._bool_cb.setCurrentIndex(1 if default else 0)
            self._cur_bool_cb.setCurrentIndex(1 if current else 0)
        elif vtype == "int":
            self._int_spin.setValue(int(default) if default is not None else 0)
            self._cur_int_spin.setValue(int(current) if current is not None else 0)
        else:
            self._str_default_e.setText(str(default) if default is not None else "")
            self._choices_e.setText(", ".join(v.get("choices", [])))
            self._cur_str_e.setText(str(current) if current is not None else "")

    def _on_ok(self):
        name = self._name_e.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Имя переменной не может быть пустым.")
            return
        vtype = self._type_cb.currentData()
        desc  = self._desc_e.text().strip()
        if vtype == "bool":
            default = self._bool_cb.currentData()
            current = self._cur_bool_cb.currentData() if self._existing else default
            choices = []
        elif vtype == "int":
            default = self._int_spin.value()
            current = self._cur_int_spin.value() if self._existing else default
            choices = []
        else:
            default = self._str_default_e.text().strip()
            raw_ch  = self._choices_e.text()
            choices = [s.strip() for s in raw_ch.split(",") if s.strip()] if raw_ch.strip() else []
            current = self._cur_str_e.text().strip() if self._existing else default
        self._result = {
            "name": name, "type": vtype, "default": default,
            "choices": choices, "description": desc,
            "current": current,
            "original_name": self._original_name,
        }
        self.accept()

    def get_result(self) -> dict | None:
        return self._result


# ── Main page ─────────────────────────────────────────────────────────────────

class StatePage(QWidget):
    """
    Page for managing StateStore variables.
    Shown in sidebar between Monitor and Journal.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, VarRow] = {}   # name → VarRow
        self._build()
        self._connect_signals()
        self._refresh()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(64)
        topbar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        tb = QHBoxLayout(topbar); tb.setContentsMargins(24, 0, 24, 0); tb.setSpacing(12)

        title = QLabel("Переменные состояния")
        title.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;background:transparent;")
        tb.addWidget(title)
        tb.addStretch()

        # Reset button
        self._btn_reset = QPushButton("↺ Сброс всех")
        self._btn_reset.setFixedHeight(32)
        self._btn_reset.setToolTip("Сбросить все переменные к значению по умолчанию")
        self._btn_reset.setStyleSheet(
            f"QPushButton{{background:{c['bg_elevated']};color:{c['amber']};"
            f"border:1px solid {c['amber_dim']};border-radius:4px;"
            f"padding:4px 14px;font-size:{FONTS['size_sm']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['amber_dim']};border-color:{c['amber']};}}")
        self._btn_reset.clicked.connect(self._on_reset_all)
        tb.addWidget(self._btn_reset)

        # Add button
        self._btn_add = QPushButton("+ Добавить переменную")
        self._btn_add.setFixedHeight(32)
        self._btn_add.setStyleSheet(_btn_style())
        self._btn_add.clicked.connect(self._on_add)
        tb.addWidget(self._btn_add)

        root.addWidget(topbar)

        # ── Header row ───────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(32)
        hdr.setStyleSheet(
            f"background:{c['bg_deep']};border-bottom:1px solid {c['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 8, 0); hl.setSpacing(10)

        def _h(text, w=None):
            l = QLabel(text)
            l.setStyleSheet(
                f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
                f"font-weight:700;letter-spacing:1px;background:transparent;")
            if w:
                l.setFixedWidth(w)
            return l

        hl.addWidget(_h("ТИП", 38))
        hl.addWidget(_h("ИМЯ", 160))
        hl.addWidget(_h("ОПИСАНИЕ"), 1)
        hl.addWidget(_h("DEFAULT", 100))
        hl.addWidget(_h("ТЕКУЩЕЕ", 110))
        hl.addWidget(_h("", 66))   # buttons placeholder

        root.addWidget(hdr)

        # ── Scroll area ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{c['bg_main']};border:none;}}"
            f"QScrollBar:vertical{{background:{c['bg_deep']};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{c['border_bright']};border-radius:3px;}}")
        inner = QWidget(); inner.setStyleSheet(f"background:{c['bg_main']};")
        self._list_lay = QVBoxLayout(inner)
        self._list_lay.setContentsMargins(12, 10, 12, 10); self._list_lay.setSpacing(6)
        self._list_lay.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # ── Empty state label ─────────────────────────────────────────────────
        self._empty_lbl = QLabel(
            "Нет переменных состояния.\nНажмите «+ Добавить переменную» чтобы начать.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_md']};background:transparent;")
        self._empty_lbl.hide()
        root.addWidget(self._empty_lbl)

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self):
        try:
            from core.state_store import get_state_store
            ss = get_state_store()
            ss.signals.state_changed.connect(self._on_state_changed)
            ss.signals.vars_updated.connect(self._refresh)
        except Exception as e:
            log.error(f"StatePage: signal connect failed: {e}", exc_info=True)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _refresh(self):
        """Rebuild all rows from current StateStore."""
        try:
            from core.state_store import get_state_store
            variables = get_state_store().all_vars()
        except Exception as e:
            log.error(f"StatePage._refresh: {e}", exc_info=True)
            return

        # Remove old rows not in new list
        new_names = {v["name"] for v in variables}
        for name in list(self._rows):
            if name not in new_names:
                row = self._rows.pop(name)
                self._list_lay.removeWidget(row)
                row.deleteLater()

        # Add new rows
        for var in variables:
            name = var["name"]
            if name not in self._rows:
                row = VarRow(var, self._on_delete, self._on_edit)
                self._rows[name] = row
                # Insert before stretch
                self._list_lay.insertWidget(self._list_lay.count() - 1, row)
            else:
                self._rows[name].update_value(var.get("value"))

        # Show/hide empty label
        has_vars = bool(variables)
        self._empty_lbl.setVisible(not has_vars)

    def _on_state_changed(self, name: str, value):
        """Live update when a variable changes at runtime."""
        row = self._rows.get(name)
        if row:
            row.update_value(value)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_add(self):
        dlg = VarDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result:
                try:
                    from core.state_store import get_state_store
                    ok = get_state_store().add_var(
                        name=result["name"],
                        var_type=result["type"],
                        default=result["default"],
                        choices=result["choices"],
                        description=result["description"],
                    )
                    if not ok:
                        QMessageBox.warning(
                            self, "Ошибка",
                            f"Переменная '{result['name']}' уже существует.")
                except Exception as e:
                    log.error(f"StatePage._on_add: {e}", exc_info=True)

    def _on_edit(self, name: str):
        try:
            from core.state_store import get_state_store
            ss = get_state_store()
            var = next((v for v in ss.all_vars() if v["name"] == name), None)
            if not var:
                return
            dlg = VarDialog(existing=var, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                result = dlg.get_result()
                if result:
                    # Rename if name changed
                    new_name = result["name"]
                    if new_name != name:
                        ok = ss.rename_var(name, new_name)
                        if not ok:
                            QMessageBox.warning(
                                self, "Ошибка",
                                f"Переменная '{new_name}' уже существует.")
                            return
                        name = new_name  # update for subsequent calls
                    ss.update_var(
                        name,
                        type=result["type"],
                        default=result["default"],
                        choices=result["choices"],
                        description=result["description"],
                    )
                    # Apply current value immediately (runtime set)
                    if "current" in result:
                        ss.set(name, result["current"])
        except Exception as e:
            log.error(f"StatePage._on_edit: {e}", exc_info=True)

    def _on_delete(self, name: str):
        reply = QMessageBox.question(
            self, "Удалить переменную",
            f"Удалить переменную «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from core.state_store import get_state_store
                get_state_store().remove_var(name)
            except Exception as e:
                log.error(f"StatePage._on_delete: {e}", exc_info=True)

    def _on_reset_all(self):
        reply = QMessageBox.question(
            self, "Сброс переменных",
            "Сбросить все переменные состояния к значениям по умолчанию?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from core.state_store import get_state_store
                get_state_store().reset_all()
                self._refresh()
            except Exception as e:
                log.error(f"StatePage._on_reset_all: {e}", exc_info=True)
