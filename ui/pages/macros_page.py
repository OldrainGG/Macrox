"""
MacroX — Macros Page
Integrates with MacroEngine: toggle active, register/unregister on save/delete.

Fixes:
  - btn_new connected correctly (was using hasattr guard that always failed)
  - MacroCard.refresh() now updates detail_lbl and hk_lbl
  - Condition UI (Variant A: macro-level) added to MacroEditorPanel
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSpinBox, QLineEdit, QCheckBox,
    QMessageBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from ui.theme import COLORS, FONTS
from ui.hotkey_capture import HotkeyCaptureDialog
from ui.macro_recorder import MacroRecorderDialog, MODE_LABELS
from core.logger import trace_calls
from core.macro_store import get_store
from core.macro_engine import get_engine

log = logging.getLogger(__name__)

# Scroll-wheel blocker
from PyQt6.QtCore import QObject, QEvent as _QEvent
class _NoScrollFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == _QEvent.Type.Wheel:
            event.ignore(); return True
        return False
_no_scroll = _NoScrollFilter()


class MacroCard(QFrame):
    deleted        = pyqtSignal(object)
    edit_requested = pyqtSignal(object)
    toggled        = pyqtSignal(object, bool)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self._build()

    def _build(self):
        c = COLORS
        self.setStyleSheet(
            f"QFrame#MacroCard{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:8px;}}"
            f"QFrame#MacroCard:hover{{border-color:{c['border_bright']};}}"
            f"QLabel{{background:transparent;border:none;}}"
        )
        self.setObjectName("MacroCard")
        self.setFixedHeight(88)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14,10,14,10); lay.setSpacing(10)

        # Active toggle
        active = self.data.get("active", False)
        self.toggle_btn = QPushButton("▶" if not active else "⏸")
        self.toggle_btn.setFixedSize(38, 38)
        self.toggle_btn.setToolTip("Активировать / Деактивировать макрос")
        self._apply_toggle_style(active)
        self.toggle_btn.clicked.connect(self._on_toggle)
        lay.addWidget(self.toggle_btn)

        # Info
        info = QVBoxLayout(); info.setSpacing(4)
        self.name_lbl = QLabel(self.data.get("name","Макрос"))
        self.name_lbl.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};font-weight:600;")
        self.detail_lbl = QLabel(self._make_detail())
        self.detail_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};")
        info.addWidget(self.name_lbl); info.addWidget(self.detail_lbl)
        lay.addLayout(info); lay.addStretch()

        # Condition badge (shown if macro has condition)
        self.cond_lbl = QLabel()
        self.cond_lbl.setFixedHeight(22)
        self.cond_lbl.setStyleSheet(
            f"color:{c['amber']};background:{c['amber_dim']};"
            f"border:1px solid {c['amber']};border-radius:3px;"
            f"padding:1px 6px;font-size:{FONTS['size_xs']};")
        self._update_cond_badge()
        lay.addWidget(self.cond_lbl)

        # Hotkey badge
        self.hk_lbl = QLabel(self.data.get("hotkey","—") or "—")
        self.hk_lbl.setFixedWidth(84)
        self.hk_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hk_lbl.setToolTip("Горячая клавиша запуска")
        self.hk_lbl.setStyleSheet(
            f"color:{c['accent_bright']};background:{c['accent_dim']};"
            f"border:1px solid {c['accent']};border-radius:4px;"
            f"padding:3px 8px;font-size:{FONTS['size_sm']};font-family:{FONTS['mono']};")
        lay.addWidget(self.hk_lbl)

        # Action buttons
        for text, tip, slot, danger in [
            ("✏  Изменить", "Редактировать макрос",
             lambda: self.edit_requested.emit(self), False),
            ("🗑  Удалить",  "Удалить этот макрос",
             lambda: self.deleted.emit(self), True),
        ]:
            b = QPushButton(text); b.setFixedHeight(30); b.setMinimumWidth(95)
            b.setToolTip(tip)
            bg  = c['danger_dim'] if danger else c['bg_elevated']
            fg  = c['danger']     if danger else c['text_secondary']
            brd = c['danger']     if danger else c['border']
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:1px solid {brd};"
                f"border-radius:5px;font-size:{FONTS['size_xs']};font-weight:600;padding:0 10px;}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}")
            b.clicked.connect(slot)
            lay.addWidget(b)

    def _make_detail(self) -> str:
        steps  = self.data.get("steps", [])
        mode   = MODE_LABELS[self.data.get("mode", 0)]
        delay  = self.data.get("delay_ms", 0)
        rand   = self.data.get("random_ms", 0)
        cond   = self.data.get("condition") or {}
        # Macro-level launch condition badge
        cond_badge = ""
        if cond.get("state_var"):
            op  = cond.get("op", "==")
            val = cond.get("value", "")
            cond_badge = f"  •  🔒 {cond['state_var']} {op} {val}"
        elif cond.get("zone_id") is not None:
            cond_badge = f"  •  🔒 zone#{cond['zone_id']} {cond.get('state','match')}"
        # Step-level conditions badge
        step_cond_count = sum(1 for s in steps if s.get("condition"))
        step_badge = f"  •  🔒×{step_cond_count} шагов" if step_cond_count else ""
        if steps:
            ks = " → ".join(s["key"] for s in steps[:7])
            if len(steps) > 7: ks += f" +{len(steps)-7}"
            return f"{ks}   •   {mode}   •   {len(steps)} шагов{cond_badge}{step_badge}"
        return (f"Задержка: {delay}мс"
                + (f" ±{rand}мс" if rand else "")
                + f"   •   {mode}{cond_badge}{step_badge}")

    def _update_cond_badge(self):
        cond = self.data.get("condition") or {}
        if cond.get("state_var"):
            op  = cond.get("op", "==")
            val = cond.get("value", "")
            self.cond_lbl.setText(f"🔒 {cond['state_var']} {op} {val}")
            self.cond_lbl.show()
        elif cond.get("zone_id") is not None:
            self.cond_lbl.setText(f"🔒 zone#{cond['zone_id']} {cond.get('state','match')}")
            self.cond_lbl.show()
        else:
            self.cond_lbl.hide()

    def _on_toggle(self):
        new_active = not self.data.get("active", False)
        self.data["active"] = new_active
        self._apply_toggle_style(new_active)
        self.toggle_btn.setText("⏸" if new_active else "▶")
        self.toggled.emit(self, new_active)

    def _apply_toggle_style(self, active: bool):
        c = COLORS
        if active:
            self.toggle_btn.setStyleSheet(
                f"QPushButton{{background:{c['success_dim']};color:{c['success']};"
                f"border:2px solid {c['success']};border-radius:6px;"
                f"font-size:16px;font-weight:700;}}"
                f"QPushButton:hover{{background:{c['success']};color:white;}}")
        else:
            self.toggle_btn.setStyleSheet(
                f"QPushButton{{background:{c['bg_elevated']};color:{c['text_muted']};"
                f"border:1px solid {c['border']};border-radius:6px;font-size:14px;}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}")

    def refresh(self, data: dict):
        """Update card — fixes: now updates detail, hotkey, condition badge."""
        self.data = data
        self.name_lbl.setText(data.get("name", ""))
        self.detail_lbl.setText(self._make_detail())
        self.hk_lbl.setText(data.get("hotkey", "—") or "—")
        self._apply_toggle_style(data.get("active", False))
        self.toggle_btn.setText("⏸" if data.get("active") else "▶")
        self._update_cond_badge()


# ── Macro-level condition widget (Variant A) ──────────────────────────────────
class MacroConditionWidget(QWidget):
    """
    Compact widget for setting a macro-level condition.
    Supports two modes:
      - Zone:  {"zone_id": N, "state": "match"|"no_match"}
      - State: {"state_var": "hp_pct", "op": "<=", "value": 30}
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._zones: list[dict] = []
        self._build()
        self._load_zones()
        self._load_state_vars()

    def _build(self):
        c = COLORS
        self.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)

        # Enable checkbox
        self.enabled_cb = QCheckBox("Условие запуска макроса")
        self.enabled_cb.setStyleSheet(
            f"QCheckBox{{color:{c['text_secondary']};font-size:{FONTS['size_sm']};"
            f"spacing:6px;background:transparent;}}"
            f"QCheckBox::indicator{{width:14px;height:14px;border-radius:3px;"
            f"border:1px solid {c['border_bright']};background:{c['bg_panel']};}}"
            f"QCheckBox::indicator:checked{{background:{c['accent']};"
            f"border-color:{c['accent']};}}")
        self.enabled_cb.stateChanged.connect(self._on_toggle)
        lay.addWidget(self.enabled_cb)

        wrap = QWidget(); wrap.setStyleSheet("background:transparent;")
        wl   = QVBoxLayout(wrap); wl.setContentsMargins(20,0,0,0); wl.setSpacing(6)

        # Mode switcher: Zone | State variable
        mode_row = QWidget(); mode_row.setStyleSheet("background:transparent;")
        ml = QHBoxLayout(mode_row); ml.setContentsMargins(0,0,0,0); ml.setSpacing(6)
        mode_lbl = QLabel("Тип условия:")
        mode_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
        ml.addWidget(mode_lbl)
        self._mode_cb = QComboBox()
        self._mode_cb.addItem("Зона мониторинга", "zone")
        self._mode_cb.addItem("Переменная состояния", "state")
        self._mode_cb.setFixedHeight(26)
        self._mode_cb.setStyleSheet(self._cb_style())
        self._mode_cb.installEventFilter(_no_scroll)
        self._mode_cb.currentIndexChanged.connect(self._on_mode_change)
        ml.addWidget(self._mode_cb)
        ml.addStretch()
        wl.addWidget(mode_row)

        # ── Zone panel ────────────────────────────────────────────────────
        self._zone_panel = QWidget(); self._zone_panel.setStyleSheet("background:transparent;")
        zl = QHBoxLayout(self._zone_panel); zl.setContentsMargins(0,0,0,0); zl.setSpacing(8)

        zone_lbl = QLabel("Зона:")
        zone_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
        zl.addWidget(zone_lbl)

        self._zone_cb = QComboBox()
        self._zone_cb.setFixedHeight(26)
        self._zone_cb.setMinimumWidth(160)
        self._zone_cb.setStyleSheet(self._cb_style())
        self._zone_cb.installEventFilter(_no_scroll)
        zl.addWidget(self._zone_cb)

        state_lbl = QLabel("Состояние:")
        state_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
        zl.addWidget(state_lbl)

        self._state_cb = QComboBox()
        self._state_cb.addItem("совпадает (match)",    "match")
        self._state_cb.addItem("не совпадает (no_match)", "no_match")
        self._state_cb.setFixedHeight(26)
        self._state_cb.setStyleSheet(self._cb_style())
        self._state_cb.installEventFilter(_no_scroll)
        zl.addWidget(self._state_cb)
        zl.addStretch()
        wl.addWidget(self._zone_panel)

        # ── State variable panel ──────────────────────────────────────────
        self._state_panel = QWidget(); self._state_panel.setStyleSheet("background:transparent;")
        sg = QGridLayout(self._state_panel)
        sg.setContentsMargins(0,0,0,0); sg.setHorizontalSpacing(6); sg.setVerticalSpacing(4)

        def _slbl(text):
            l = QLabel(text)
            l.setStyleSheet(
                f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
            return l

        sg.addWidget(_slbl("Переменная:"), 0, 0)
        self._var_cb = QComboBox()
        self._var_cb.setFixedHeight(26)
        self._var_cb.setMaximumWidth(160)
        self._var_cb.setStyleSheet(self._cb_style())
        self._var_cb.installEventFilter(_no_scroll)
        self._var_cb.currentIndexChanged.connect(self._on_var_change)
        sg.addWidget(self._var_cb, 1, 0)

        sg.addWidget(_slbl("Оператор:"), 0, 1)
        self._op_cb = QComboBox()
        self._op_cb.setFixedHeight(26)
        self._op_cb.setFixedWidth(60)
        self._op_cb.setStyleSheet(self._cb_style())
        self._op_cb.installEventFilter(_no_scroll)
        sg.addWidget(self._op_cb, 1, 1)

        sg.addWidget(_slbl("Значение:"), 0, 2)
        self._val_e = QLineEdit()
        self._val_e.setFixedHeight(26)
        self._val_e.setMaximumWidth(100)
        self._val_e.setStyleSheet(
            f"QLineEdit{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border_bright']};border-radius:4px;"
            f"padding:2px 6px;font-size:{FONTS['size_xs']};}}"
            f"QLineEdit:focus{{border-color:{c['accent']};}}")
        sg.addWidget(self._val_e, 1, 2)

        # Bool value combobox (shown instead of text field for bool vars)
        self._val_bool_cb = QComboBox()
        self._val_bool_cb.addItem("False", "False")
        self._val_bool_cb.addItem("True", "True")
        self._val_bool_cb.setFixedHeight(26)
        self._val_bool_cb.setMaximumWidth(100)
        self._val_bool_cb.setStyleSheet(self._cb_style())
        self._val_bool_cb.installEventFilter(_no_scroll)
        self._val_bool_cb.hide()
        sg.addWidget(self._val_bool_cb, 1, 2)

        sg.setColumnStretch(3, 1)   # absorb leftover space
        wl.addWidget(self._state_panel)

        # Hint
        self._hint = QLabel("")
        self._hint.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-style:italic;")
        wl.addWidget(self._hint)

        lay.addWidget(wrap)
        self._wrap = wrap
        wrap.hide()

        self._on_mode_change()

    def _on_toggle(self, state):
        enabled = bool(state)
        self._wrap.setVisible(enabled)

    def _on_mode_change(self, _=None):
        mode = self._mode_cb.currentData() if self._mode_cb.count() else "zone"
        self._zone_panel.setVisible(mode == "zone")
        self._state_panel.setVisible(mode == "state")
        if mode == "zone":
            self._hint.setText("Макрос запустится только если зона в нужном состоянии")
        else:
            self._hint.setText("Макрос запустится только если переменная удовлетворяет условию")

    def _on_var_change(self, _=None):
        """Update operator list and value widget based on selected variable type."""
        vtype = self._var_cb.currentData()
        self._op_cb.clear()
        if vtype == "int":
            for op in ("==", "!=", "<", "<=", ">", ">="):
                self._op_cb.addItem(op, op)
            self._val_e.show(); self._val_bool_cb.hide()
        elif vtype == "bool":
            self._op_cb.addItem("==", "==")
            self._op_cb.addItem("!=", "!=")
            self._val_e.hide(); self._val_bool_cb.show()
        else:  # str
            self._op_cb.addItem("==", "==")
            self._op_cb.addItem("!=", "!=")
            self._val_e.show(); self._val_bool_cb.hide()

    def _load_zones(self):
        try:
            from core.monitor_store import get_monitor_store
            store = get_monitor_store()
            sid   = store.active_scene_id()
            self._zones = store.zones_for(sid) if sid else []
            self._zone_cb.clear()
            self._zone_cb.addItem("— не выбрана —", None)
            for z in self._zones:
                self._zone_cb.addItem(
                    f"{z.get('name','?')}  (#{z['id']})", z["id"])
        except Exception as e:
            log.debug(f"MacroConditionWidget._load_zones: {e}")

    def _load_state_vars(self):
        try:
            from core.state_store import get_state_store
            self._var_cb.clear()
            self._var_cb.addItem("— не выбрана —", None)
            for v in get_state_store().all_vars():
                self._var_cb.addItem(
                    f"{v['name']}  ({v['type']})", v["type"])
                # store name as item data by using a tuple trick via setItemData
                idx = self._var_cb.count() - 1
                self._var_cb.setItemData(idx, v["name"], Qt.ItemDataRole.UserRole + 1)
        except Exception as e:
            log.debug(f"MacroConditionWidget._load_state_vars: {e}")
        self._on_var_change()

    def refresh_zones(self):
        cur = self._zone_cb.currentData()
        self._load_zones()
        if cur is not None:
            idx = self._zone_cb.findData(cur)
            if idx >= 0:
                self._zone_cb.setCurrentIndex(idx)

    def refresh_state_vars(self):
        self._load_state_vars()

    def get_condition(self) -> dict | None:
        if not self.enabled_cb.isChecked():
            return None
        mode = self._mode_cb.currentData()
        if mode == "zone":
            zone_id = self._zone_cb.currentData()
            if zone_id is None:
                return None
            return {"zone_id": zone_id, "state": self._state_cb.currentData()}
        else:
            # state var
            idx = self._var_cb.currentIndex()
            if idx <= 0:
                return None
            var_name = self._var_cb.itemData(idx, Qt.ItemDataRole.UserRole + 1)
            vtype    = self._var_cb.currentData()
            op       = self._op_cb.currentData() or "=="
            if vtype == "bool":
                raw = self._val_bool_cb.currentData()
                value = raw == "True"
            elif vtype == "int":
                try:
                    value = int(self._val_e.text())
                except ValueError:
                    value = 0
            else:
                value = self._val_e.text()
            return {"state_var": var_name, "op": op, "value": value}

    def set_condition(self, cond: dict | None):
        if not cond:
            self.enabled_cb.setChecked(False)
            return
        self.enabled_cb.setChecked(True)
        if "zone_id" in cond:
            self._mode_cb.setCurrentIndex(0)
            self._on_mode_change()
            self._load_zones()
            idx = self._zone_cb.findData(cond["zone_id"])
            if idx >= 0:
                self._zone_cb.setCurrentIndex(idx)
            state_idx = self._state_cb.findData(cond.get("state", "match"))
            if state_idx >= 0:
                self._state_cb.setCurrentIndex(state_idx)
        elif "state_var" in cond:
            self._mode_cb.setCurrentIndex(1)
            self._on_mode_change()
            self._load_state_vars()
            var_name = cond["state_var"]
            for i in range(self._var_cb.count()):
                if self._var_cb.itemData(i, Qt.ItemDataRole.UserRole + 1) == var_name:
                    self._var_cb.setCurrentIndex(i)
                    break
            self._on_var_change()
            op_idx = self._op_cb.findData(cond.get("op", "=="))
            if op_idx >= 0:
                self._op_cb.setCurrentIndex(op_idx)
            value = cond.get("value")
            vtype = self._var_cb.currentData()
            if vtype == "bool":
                self._val_bool_cb.setCurrentIndex(1 if value else 0)
            else:
                self._val_e.setText(str(value) if value is not None else "")
        else:
            self.enabled_cb.setChecked(False)

    def _cb_style(self) -> str:
        c = COLORS
        return (f"QComboBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
                f"border:1px solid {c['border_bright']};border-radius:4px;"
                f"padding:2px 6px;font-size:{FONTS['size_xs']};}}"
                f"QComboBox QAbstractItemView{{background:{c['bg_elevated']};"
                f"color:{c['text_primary']};border:1px solid {c['accent']};"
                f"selection-background-color:{c['accent_dim']};}}")


# ── Editor panel ──────────────────────────────────────────────────────────────
class MacroEditorPanel(QWidget):
    macro_saved = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps   = []
        self._mode    = 0
        self._edit_id = None
        self._build()

    def _build(self):
        c = COLORS
        self.setStyleSheet(
            f"QWidget#EditorPanel{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:10px;}}"
            f"QLabel{{background:transparent;border:none;}}"
        )
        self.setObjectName("EditorPanel")
        self.setFixedWidth(400)

        # Outer scroll so editor doesn't overflow on small screens
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{c['bg_card']};border:none;}}"
            f"QScrollBar:vertical{{background:{c['bg_deep']};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{c['border_bright']};border-radius:3px;"
            f"min-height:20px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}")
        outer.addWidget(scroll)
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner); lay.setContentsMargins(18,18,18,18); lay.setSpacing(11)

        hdr = QLabel("Редактор макроса")
        hdr.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_lg']};font-weight:700;")
        lay.addWidget(hdr)
        lay.addWidget(self._sep())

        self._lbl(lay, "Название макроса")
        self.name_edit = self._inp("Например: Авто-клик ПКМ")
        lay.addWidget(self.name_edit)

        self._lbl(lay, "Макрокод — записанные нажатия")
        self.preview = QLabel("Не задано")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            f"color:{c['text_muted']};background:{c['bg_deep']};"
            f"border:1px solid {c['border']};border-radius:6px;"
            f"padding:7px 10px;font-size:{FONTS['size_xs']};"
            f"font-family:{FONTS['mono']};min-height:34px;")
        lay.addWidget(self.preview)

        btn_rec = QPushButton("⏺  Открыть редактор макрокода")
        btn_rec.setFixedHeight(34)
        btn_rec.setStyleSheet(self._btn_s())
        btn_rec.clicked.connect(self._open_rec)
        lay.addWidget(btn_rec)

        self._lbl(lay, "Задержка между повторами (мс)")
        dr = QHBoxLayout(); dr.setSpacing(6)
        self.delay_sp = self._spin(1, 999999, 100, " мс")
        pm = QLabel("±"); pm.setStyleSheet(f"color:{c['text_muted']};font-size:15px;")
        self.rand_sp = self._spin(0, 9999, 0, " мс")
        self.rand_sp.setToolTip("Случайное отклонение ±мс (гуманизация)")
        dr.addWidget(self.delay_sp); dr.addWidget(pm); dr.addWidget(self.rand_sp)
        lay.addLayout(dr)
        self.range_lbl = QLabel("Диапазон: 100 — 100 мс")
        self.range_lbl.setStyleSheet(
            f"color:{c['accent_bright']};font-size:{FONTS['size_xs']};")
        lay.addWidget(self.range_lbl)
        self.delay_sp.valueChanged.connect(self._upd_range)
        self.rand_sp.valueChanged.connect(self._upd_range)

        self._lbl(lay, "Горячая клавиша запуска")
        hkr = QHBoxLayout(); hkr.setSpacing(8)
        self.hk_edit = QLineEdit()
        self.hk_edit.setReadOnly(True)
        self.hk_edit.setPlaceholderText("Нажмите «🎯 Назначить» →")
        self.hk_edit.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:6px 10px;color:{c['accent_bright']};"
            f"font-family:{FONTS['mono']};font-size:{FONTS['size_md']};")
        btn_hk = QPushButton("🎯  Назначить")
        btn_hk.setFixedHeight(34)
        btn_hk.setStyleSheet(self._btn_s())
        btn_hk.clicked.connect(self._open_hk)
        hkr.addWidget(self.hk_edit, 1); hkr.addWidget(btn_hk)
        lay.addLayout(hkr)

        self.human_cb = QCheckBox("Гуманизация (случайная задержка ±)")
        self.human_cb.setChecked(True)
        self.human_cb.setStyleSheet(
            f"color:{c['text_secondary']};font-size:{FONTS['size_sm']};")
        lay.addWidget(self.human_cb)

        # ── Condition section (Variant A) ─────────────────────────────────
        lay.addWidget(self._sep())
        cond_hdr = QLabel("🔒  Условие запуска")
        cond_hdr.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_sm']};font-weight:700;")
        lay.addWidget(cond_hdr)

        self.cond_widget = MacroConditionWidget()
        lay.addWidget(self.cond_widget)

        # ── Step-level condition hint ──────────────────────────────────────
        lay.addWidget(self._sep())
        step_cond_lbl = QLabel("⚙  Условия на шаги (Вариант B)")
        step_cond_lbl.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_sm']};font-weight:700;")
        lay.addWidget(step_cond_lbl)
        step_hint = QLabel(
            "Условия для отдельных шагов настраиваются\n"
            "в редакторе макрокода (кнопка ⏺ выше)")
        step_hint.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-style:italic;")
        lay.addWidget(step_hint)

        lay.addStretch()

        self.save_btn = QPushButton("💾  Сохранить макрос")
        self.save_btn.setFixedHeight(40)
        self.save_btn.setStyleSheet(
            f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
            f"border:1px solid {c['accent']};border-radius:8px;"
            f"font-size:{FONTS['size_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent']};color:white;}}")
        self.save_btn.clicked.connect(self._save)
        lay.addWidget(self.save_btn)

    @trace_calls
    def _open_rec(self):
        dlg = MacroRecorderDialog(existing_steps=self._steps, parent=self)
        dlg.recording_done.connect(self._on_recorded)
        dlg.exec()

    @trace_calls
    def _on_recorded(self, steps: list, mode: int):
        self._steps = steps; self._mode = mode
        self._upd_preview()
        # Refresh zone list in condition widget (scene may have changed)
        self.cond_widget.refresh_zones()

    def _upd_preview(self):
        if not self._steps:
            self.preview.setText("Не задано"); return
        parts = [s["key"] for s in self._steps[:8]]
        if len(self._steps) > 8: parts.append(f"+{len(self._steps)-8}")
        # Count steps with conditions (Variant B)
        cond_count = sum(1 for s in self._steps if s.get("condition"))
        total = sum(s["delay_ms"] for s in self._steps)
        cond_str = f"  •  🔒{cond_count} с условием" if cond_count else ""
        self.preview.setText(
            f"{' → '.join(parts)}\n"
            f"{len(self._steps)} шагов  •  ~{total}мс  •  "
            f"{MODE_LABELS[self._mode]}{cond_str}")

    @trace_calls
    def _open_hk(self):
        dlg = HotkeyCaptureDialog(current_hotkey=self.hk_edit.text(), parent=self)
        dlg.hotkey_captured.connect(self.hk_edit.setText)
        dlg.exec()

    def _upd_range(self):
        d, r = self.delay_sp.value(), self.rand_sp.value()
        self.range_lbl.setText(f"Диапазон: {max(0,d-r)} — {d+r} мс")

    @trace_calls
    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название макроса"); return
        if not self._steps:
            QMessageBox.warning(self, "Ошибка", "Запишите хотя бы одно нажатие клавиши"); return

        # Preserve active state for existing macros — don't reset it on edit
        if self._edit_id is not None:
            existing = get_store().get(self._edit_id)
            current_active = existing.get("active", False) if existing else False
        else:
            current_active = False

        data = {
            "name":      name,
            "steps":     self._steps,
            "mode":      self._mode,
            "delay_ms":  self.delay_sp.value(),
            "random_ms": self.rand_sp.value(),
            "hotkey":    self.hk_edit.text(),
            "humanize":  self.human_cb.isChecked(),
            "active":    current_active,
            "condition": self.cond_widget.get_condition(),
        }
        store = get_store()
        if self._edit_id is not None:
            data["id"] = self._edit_id
            store.update(self._edit_id, data)
            log.info(f"Macro updated: id={self._edit_id} name='{name}'")
        else:
            new_id = store.add(data)
            self._edit_id = new_id
            data["id"]    = new_id
            log.info(f"Macro created: id={new_id} name='{name}'")

        get_engine().register(data)
        self.macro_saved.emit(data)

    @trace_calls
    def load_macro(self, data: dict):
        self._edit_id = data.get("id")
        self.name_edit.setText(data.get("name", ""))
        self._steps = data.get("steps", [])
        self._mode  = data.get("mode", 0)
        self.delay_sp.setValue(data.get("delay_ms", 100))
        self.rand_sp.setValue(data.get("random_ms", 0))
        self.hk_edit.setText(data.get("hotkey", ""))
        self.human_cb.setChecked(data.get("humanize", True))
        self.cond_widget.set_condition(data.get("condition"))
        self._upd_preview()

    @trace_calls
    def clear(self):
        self._edit_id = None
        self.name_edit.clear(); self._steps = []; self._mode = 0
        self.delay_sp.setValue(100); self.rand_sp.setValue(0)
        self.hk_edit.clear(); self.preview.setText("Не задано")
        self.human_cb.setChecked(True); self._upd_range()
        self.cond_widget.set_condition(None)

    # ── Style helpers ─────────────────────────────────────────────────────
    def _sep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{COLORS['border']};max-height:1px;border:none;")
        return f

    def _lbl(self, lay, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_sm']};font-weight:600;")
        lay.addWidget(l)

    def _inp(self, ph=""):
        c = COLORS; e = QLineEdit(); e.setPlaceholderText(ph)
        e.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:6px 10px;color:{c['text_primary']};"
            f"font-size:{FONTS['size_md']};")
        return e

    def _spin(self, lo, hi, val, suf=""):
        c = COLORS; s = QSpinBox()
        s.setRange(lo, hi); s.setValue(val); s.setSuffix(suf)
        s.setStyleSheet(
            f"QSpinBox{{background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:5px 7px;color:{c['text_primary']};"
            f"font-size:{FONTS['size_md']};}}"
            f"QSpinBox:focus{{border-color:{c['accent']};}}"
            f"QSpinBox::up-button,QSpinBox::down-button{{"
            f"background:{c['bg_elevated']};border:none;width:16px;}}")
        return s

    def _btn_s(self):
        c = COLORS
        return (f"QPushButton{{background:{c['bg_elevated']};color:{c['text_secondary']};"
                f"border:1px solid {c['border_bright']};border-radius:6px;"
                f"font-size:{FONTS['size_sm']};}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['accent_bright']};"
                f"border-color:{c['accent']};}}")


# ── Macros Page ───────────────────────────────────────────────────────────────
class MacrosPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[MacroCard] = []
        self._build()
        self._load_from_store()

    def _build(self):
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header bar
        bar = QWidget(); bar.setFixedHeight(64)
        bar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(24,0,24,0)
        tv = QVBoxLayout(); tv.setSpacing(1)
        t = QLabel("Макросы")
        t.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};font-weight:700;"
            f"background:transparent;")
        s = QLabel("Управление и настройка макросов")
        s.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};background:transparent;")
        tv.addWidget(t); tv.addWidget(s)
        bl.addLayout(tv); bl.addStretch()

        self.active_count_lbl = QLabel("")
        self.active_count_lbl.setStyleSheet(
            f"color:{c['success']};font-size:{FONTS['size_sm']};font-weight:600;"
            f"background:transparent;")
        bl.addWidget(self.active_count_lbl)

        btn_new = QPushButton("＋  Новый макрос")
        btn_new.setFixedHeight(36)
        btn_new.setStyleSheet(
            f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
            f"border:1px solid {c['accent']};border-radius:6px;padding:0 18px;"
            f"font-size:{FONTS['size_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent']};color:white;}}")
        bl.addWidget(btn_new)
        root.addWidget(bar)

        content = QWidget()
        cl = QHBoxLayout(content); cl.setContentsMargins(24,24,24,24); cl.setSpacing(20)

        list_w = QWidget()
        ll = QVBoxLayout(list_w); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        lhdr = QLabel("СПИСОК МАКРОСОВ")
        lhdr.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;")
        ll.addWidget(lhdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;border:none;")
        self.list_inner = QWidget(); self.list_inner.setStyleSheet("background:transparent;")
        self.list_lay = QVBoxLayout(self.list_inner)
        self.list_lay.setContentsMargins(0,0,0,0); self.list_lay.setSpacing(8)
        self.list_lay.addStretch()
        scroll.setWidget(self.list_inner)
        ll.addWidget(scroll)

        self.editor = MacroEditorPanel()
        self.editor.macro_saved.connect(self._on_macro_saved)
        btn_new.clicked.connect(self.editor.clear)   # Fix: direct connect, no hasattr guard

        cl.addWidget(list_w, 1); cl.addWidget(self.editor)
        root.addWidget(content, 1)

    @trace_calls
    def _load_from_store(self):
        store  = get_store()
        macros = store.all()
        log.info(f"Loading {len(macros)} macros")
        for data in macros:
            self._add_card(data)
            get_engine().register(data)
        self._upd_active_count()

    @trace_calls
    def _on_macro_saved(self, data: dict):
        mid = data.get("id")
        for card in self._cards:
            if card.data.get("id") == mid:
                card.refresh(data)   # Fix: refresh in place, don't recreate
                self._upd_active_count()
                return
        self._add_card(data)
        self._upd_active_count()

    def _add_card(self, data: dict):
        card = MacroCard(data)
        card.deleted.connect(self._del_card)
        card.edit_requested.connect(lambda c: self.editor.load_macro(c.data))
        card.toggled.connect(self._on_card_toggled)
        self.list_lay.insertWidget(self.list_lay.count()-1, card)
        self._cards.append(card)

    @trace_calls
    def _on_card_toggled(self, card: MacroCard, active: bool):
        mid = card.data.get("id")
        if mid:
            get_engine().set_active(mid, active)
        self._upd_active_count()

    @trace_calls
    def _del_card(self, card: MacroCard):
        mid = card.data.get("id")
        if mid:
            get_engine().unregister(mid)
            get_store().delete(mid)
        self.list_lay.removeWidget(card); card.deleteLater()
        self._cards.remove(card)
        self._upd_active_count()

    def _upd_active_count(self):
        n = sum(1 for c in self._cards if c.data.get("active"))
        self.active_count_lbl.setText(f"▶ {n} активных" if n else "")
