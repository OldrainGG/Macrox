"""
MacroX — Monitor Page v2
Layout:
  [Scene list | Zone table + editor]
  Scene switching, priority queue, parallel flag, 10+ zones support.
"""
import logging
from io import BytesIO
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSpinBox, QComboBox,
    QLineEdit, QDoubleSpinBox, QMessageBox, QSplitter,
    QInputDialog, QCheckBox, QAbstractItemView, QSlider
)
from PyQt6.QtCore  import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui   import QPixmap, QImage, QColor, QPainter, QPen, QFont

from ui.theme      import COLORS, FONTS
from core.monitor_store  import (
    get_monitor_store, PRIORITY_LABELS, PRIORITY_COLORS
)
from core.monitor_engine import (
    get_monitor_engine, monitor_signals,
    capture_region, image_to_b64, b64_to_image
)

log = logging.getLogger(__name__)


# ── Scroll-wheel blocker (prevents accidental value changes while scrolling) ──
from PyQt6.QtCore import QObject, QEvent as _QEvent

class _NoScrollFilter(QObject):
    """Blocks wheel events on QComboBox/QSpinBox so page scroll won't change values."""
    def eventFilter(self, obj, event):
        if event.type() == _QEvent.Type.Wheel:
            event.ignore()
            return True
        return False

_no_scroll = _NoScrollFilter()


# ── Spin row: spinbox with visible +/- buttons ────────────────────────────────
class _SpinRow(QWidget):
    """[−] spinbox [+] — all elements fixed at same height, aligned center."""
    valueChanged = pyqtSignal(int)

    H = 28  # fixed height for all elements

    def __init__(self, val=0, lo=0, hi=999, suffix="  пкс",
                 w_spin=72, double=False, step=1, parent=None):
        super().__init__(parent)
        self._double = double
        self.setFixedHeight(self.H)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        c = COLORS
        btn_base = (
            f"QPushButton{{background:{c['bg_elevated']};color:#FFFFFF;"
            f"border:1px solid {c['border']};font-size:15px;font-weight:700;"
            f"width:24px;height:{self.H}px;padding:0;margin:0;line-height:{self.H}px;}}"
            f"QPushButton:hover{{background:{c['accent_dim']};"
            f"border-color:{c['accent']};color:{c['accent_bright']};}}"
            f"QPushButton:pressed{{background:{c['accent']};color:white;}}"
        )

        self._btn_m = QPushButton("−")
        self._btn_m.setFixedSize(24, self.H)
        self._btn_m.setStyleSheet(btn_base +
            f"QPushButton{{border-top-left-radius:5px;border-bottom-left-radius:5px;}}")
        self._btn_m.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_m.installEventFilter(_no_scroll)
        lay.addWidget(self._btn_m, 0, Qt.AlignmentFlag.AlignVCenter)

        if double:
            self._sp = QDoubleSpinBox()
            self._sp.setDecimals(2)
            self._sp.setSingleStep(float(step))
        else:
            self._sp = QSpinBox()
            self._sp.setSingleStep(int(step))

        self._sp.setRange(lo, hi)
        self._sp.setValue(val)
        if suffix:
            self._sp.setSuffix(suffix)
        self._sp.setFixedHeight(self.H)
        self._sp.setFixedWidth(w_spin)
        self._sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sp.setStyleSheet(
            f"QSpinBox,QDoubleSpinBox{{background:{c['bg_panel']};"
            f"color:{c['text_primary']};"
            f"border-top:1px solid {c['border']};"
            f"border-bottom:1px solid {c['border']};"
            f"border-left:none;border-right:none;"
            f"border-radius:0;padding:0 4px;"
            f"font-size:{FONTS['size_sm']};margin:0;}}"
        )
        self._sp.installEventFilter(_no_scroll)
        lay.addWidget(self._sp, 0, Qt.AlignmentFlag.AlignVCenter)

        self._btn_p = QPushButton("+")
        self._btn_p.setFixedSize(24, self.H)
        self._btn_p.setStyleSheet(btn_base +
            f"QPushButton{{border-top-right-radius:5px;border-bottom-right-radius:5px;}}")
        self._btn_p.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_p.installEventFilter(_no_scroll)
        lay.addWidget(self._btn_p, 0, Qt.AlignmentFlag.AlignVCenter)

        self._btn_m.clicked.connect(lambda: self._step(-1))
        self._btn_p.clicked.connect(lambda: self._step(+1))
        self._sp.valueChanged.connect(self._on_change)

    def _step(self, d):
        if self._double:
            self._sp.setValue(self._sp.value() + d * self._sp.singleStep())
        else:
            self._sp.setValue(self._sp.value() + d)

    def _on_change(self, v):
        self.valueChanged.emit(int(v) if not self._double else int(v))

    def value(self):
        return self._sp.value()

    def setValue(self, v):
        # Block internal spinbox signal to avoid double-emit,
        # but emit our own valueChanged so connected widgets update
        old = self._sp.value()
        self._sp.blockSignals(True)
        self._sp.setValue(v)
        self._sp.blockSignals(False)
        if self._sp.value() != old:
            self.valueChanged.emit(int(self._sp.value()))


# ── Tiny image preview ────────────────────────────────────────────────────────
class ThumbLabel(QLabel):
    def __init__(self, w=80, h=44, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c = COLORS
        self.setStyleSheet(
            f"background:{c['bg_deep']};border:1px solid {c['border']};"
            f"border-radius:3px;color:{c['text_muted']};font-size:9px;")
        self.setText("—")

    def set_b64(self, b64: str):
        if not b64: self.setText("—"); return
        try:
            img  = b64_to_image(b64)
            buf  = BytesIO(); img.save(buf, format="PNG")
            qimg = QImage.fromData(buf.getvalue())
            pm   = QPixmap.fromImage(qimg).scaled(
                self.width()-2, self.height()-2,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.setPixmap(pm)
        except Exception: self.setText("ERR")


# ── LED status dot ────────────────────────────────────────────────────────────
class LedDot(QLabel):
    _C = {"idle":"#4A5068","match":"#2ECC71","no_match":"#E74C3C","error":"#F0A030"}

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self._state = "idle"; self._on = True
        self.setFixedWidth(14); self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._t = QTimer(self); self._t.setInterval(500)
        self._t.timeout.connect(self._blink)
        self._apply()

    def set_state(self, s: str):
        if s == self._state: return
        self._state = s
        if s == "match": self._t.start()
        else: self._t.stop(); self._on = True
        self._apply()

    def _blink(self):
        self._on = not self._on; self._apply()

    def _apply(self):
        col = self._C.get(self._state,"#4A5068")
        if not self._on: col = COLORS['border']
        self.setStyleSheet(
            f"color:{col};font-size:12px;background:transparent;border:none;")


# ── Zone row (compact table row) ──────────────────────────────────────────────
class ZoneRow(QFrame):
    """One row in the zone table. Compact — shows all key info inline."""
    edit_clicked   = pyqtSignal(dict)
    delete_clicked = pyqtSignal(dict)
    toggled        = pyqtSignal(dict, bool)
    priority_changed = pyqtSignal(dict, int)

    def __init__(self, zone: dict, parent=None):
        super().__init__(parent)
        self.zone = zone
        self.setObjectName("ZoneRow")
        self.setFixedHeight(54)
        self._build()

    def _build(self):
        c = COLORS
        self.setStyleSheet(
            f"QFrame#ZoneRow{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:6px;}} QLabel{{background:transparent;border:none;}}")
        lay = QHBoxLayout(self); lay.setContentsMargins(8,4,8,4); lay.setSpacing(8)

        # Active toggle (small)
        active = self.zone.get("active", False)
        self.tog = QPushButton("▶" if not active else "⏸")
        self.tog.setFixedSize(30, 30)
        self._style_tog(active)
        self.tog.clicked.connect(self._on_toggle)
        lay.addWidget(self.tog)

        # Thumb
        self.thumb = ThumbLabel(72, 40)
        self.thumb.set_b64(self.zone.get("reference",""))
        lay.addWidget(self.thumb)

        # Priority badge
        pri = self.zone.get("priority", 2)
        self.pri_cb = QComboBox()
        self.pri_cb.setFixedWidth(110); self.pri_cb.setFixedHeight(26)
        for k,v in PRIORITY_LABELS.items(): self.pri_cb.addItem(v, k)
        self.pri_cb.setCurrentIndex(pri - 1)
        self.pri_cb.setStyleSheet(self._pri_style(pri))
        self.pri_cb.currentIndexChanged.connect(self._on_priority)
        lay.addWidget(self.pri_cb)

        # Name + detail
        info = QVBoxLayout(); info.setSpacing(1)
        self.name_lbl = QLabel(self.zone.get("name","Зона"))
        self.name_lbl.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};font-weight:600;")
        rect  = self.zone.get("rect",[0,0,0,0])
        _is_tpl = self.zone.get("zone_type","pixel") == "template"
        if _is_tpl:
            cond  = "найдена" if self.zone.get("condition","found")=="found" else "не найдена"
            thr   = int(self.zone.get("match_thresh",0.75)*100)
        else:
            cond  = "совп." if self.zone.get("condition")=="match" else "≠ совп."
            thr   = int(self.zone.get("threshold",0.90)*100)
        atype = self.zone.get("action_type","key")
        act   = (self.zone.get("action_key","—") if atype=="key"
                 else f"macro #{self.zone.get('action_macro_id','—')}")
        par   = " ⚡parallel" if self.zone.get("parallel") else ""
        if _is_tpl:
            sr = self.zone.get("search_rect",[0,0,0,0]) or [0,0,0,0]
            _detail_str = f"🔍 {sr[2]}×{sr[3]}px  •  ≥{thr}%  •  {cond}  →  {act}{par}"
        else:
            _detail_str = f"{rect[2]}×{rect[3]}px  •  {cond} ≥{thr}%  →  {act}{par}"
        self.detail_lbl = QLabel(_detail_str)
        self.detail_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        info.addWidget(self.name_lbl); info.addWidget(self.detail_lbl)
        lay.addLayout(info, 1)

        # LED
        self.led = LedDot(); lay.addWidget(self.led)

        # Action buttons
        for icon, tip, fn, danger in [
            ("✏","Редактировать", lambda: self.edit_clicked.emit(self.zone), False),
            ("✕","Удалить",       lambda: self.delete_clicked.emit(self.zone), True),
        ]:
            b = QPushButton(icon); b.setFixedSize(28,28)
            bg = c['danger_dim'] if danger else c['bg_elevated']
            fg = c['danger']     if danger else c['text_muted']
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg};"
                f"border-radius:4px;font-size:11px;font-weight:700;}}"
                f"QPushButton:hover{{background:{fg};color:white;}}")
            b.setToolTip(tip); b.clicked.connect(fn); lay.addWidget(b)

    def _on_toggle(self):
        new = not self.zone.get("active", False)
        self.zone["active"] = new
        self.tog.setText("⏸" if new else "▶")
        self._style_tog(new)
        self.toggled.emit(self.zone, new)

    def _on_priority(self, idx: int):
        pri = idx + 1
        self.zone["priority"] = pri
        self.pri_cb.setStyleSheet(self._pri_style(pri))
        self.priority_changed.emit(self.zone, pri)

    def _style_tog(self, active: bool):
        c = COLORS
        if active:
            self.tog.setStyleSheet(
                f"QPushButton{{background:{c['success_dim']};color:{c['success']};"
                f"border:1px solid {c['success']};border-radius:5px;font-size:10px;}}"
                f"QPushButton:hover{{background:{c['success']};color:white;}}")
        else:
            self.tog.setStyleSheet(
                f"QPushButton{{background:{c['bg_elevated']};color:{c['text_muted']};"
                f"border:1px solid {c['border']};border-radius:5px;font-size:10px;}}"
                f"QPushButton:hover{{background:{c['bg_hover']};color:{c['text_primary']};}}")

    def _pri_style(self, pri: int) -> str:
        col  = PRIORITY_COLORS.get(pri, COLORS['text_muted'])
        bg   = col + "22"
        return (f"QComboBox{{background:{bg};color:{col};border:1px solid {col};"
                f"border-radius:4px;padding:2px 6px;font-size:{FONTS['size_xs']};"
                f"font-weight:600;}}"
                f"QComboBox QAbstractItemView{{background:{COLORS['bg_elevated']};"
                f"color:{COLORS['text_primary']};border:1px solid {COLORS['border']};"
                f"selection-background-color:{COLORS['accent_dim']};}}")

    def refresh(self, zone: dict):
        self.zone = zone
        self.name_lbl.setText(zone.get("name",""))
        self.thumb.set_b64(zone.get("reference",""))
        pri = zone.get("priority",2)
        self.pri_cb.blockSignals(True)
        self.pri_cb.setCurrentIndex(pri-1)
        self.pri_cb.blockSignals(False)
        self.pri_cb.setStyleSheet(self._pri_style(pri))
        active = zone.get("active",False)
        self.tog.setText("⏸" if active else "▶")
        self._style_tog(active)
        # Update detail line in real time (fix bug 5)
        is_tpl = zone.get("zone_type","pixel") == "template"
        rect   = zone.get("rect",[0,0,0,0]) or [0,0,0,0]
        atype  = zone.get("action_type","key")
        act    = (zone.get("action_key","—") if atype=="key"
                  else f"macro #{zone.get('action_macro_id','—')}")
        par    = " ⚡" if zone.get("parallel") else ""
        human  = f" ±{zone.get('humanize_ms',0)}мс" if zone.get('humanize_ms',0) else ""
        if is_tpl:
            sr    = zone.get("search_rect",[0,0,0,0]) or [0,0,0,0]
            thr   = int(zone.get("match_thresh", 0.75) * 100)
            cond  = "найдена" if zone.get("condition","found")=="found" else "не найдена"
            grid_s = " 🔲сетка" if zone.get("grid") else ""
            dbg_s  = " 🐛" if zone.get("debug_capture") else ""
            self.detail_lbl.setText(
                f"🔍 {sr[2]}×{sr[3]}px  •  ≥{thr}%  •  {cond}"
                f"{grid_s}{dbg_s}  →  {act}{par}{human}")
        else:
            cond  = "совп." if zone.get("condition")=="match" else "≠ совп."
            thr   = int(zone.get("threshold",0.90)*100)
            self.detail_lbl.setText(
                f"{rect[2]}×{rect[3]}px  •  {cond} ≥{thr}%"
                f"  →  {act}{par}{human}")


# ── Scene sidebar ─────────────────────────────────────────────────────────────
class ScenePanel(QWidget):
    scene_selected = pyqtSignal(int)
    scene_added    = pyqtSignal(int)
    scene_deleted  = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._btns: dict[int, QPushButton] = {}
        self._rows_map: dict[int, QWidget] = {}   # sid → row widget
        self.setFixedWidth(210)
        c = COLORS
        self.setStyleSheet(
            f"background:{c['bg_panel']};border-right:1px solid {c['border']};")
        lay = QVBoxLayout(self); lay.setContentsMargins(10,14,10,10); lay.setSpacing(6)

        hdr = QLabel("СЦЕНЫ")
        hdr.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.5px;background:transparent;")
        lay.addWidget(hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;border:none;")
        self._list_w = QWidget(); self._list_w.setStyleSheet("background:transparent;")
        self._list_l = QVBoxLayout(self._list_w)
        self._list_l.setContentsMargins(0,0,0,0); self._list_l.setSpacing(4)
        self._list_l.addStretch()
        scroll.setWidget(self._list_w)
        lay.addWidget(scroll, 1)

        add_btn = QPushButton("＋  Новая сцена")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(
            f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
            f"border:1px solid {c['accent']};border-radius:6px;"
            f"font-size:{FONTS['size_xs']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent']};color:white;}}")
        add_btn.clicked.connect(self._add_scene)
        lay.addWidget(add_btn)

        self._load()

    def _load(self):
        store = get_monitor_store()
        for s in store.scenes():
            self._add_btn(s, store.active_scene_id() == s["id"])

    def _add_btn(self, scene: dict, active: bool = False):
        c   = COLORS
        sid = scene["id"]
        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl  = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0); rl.setSpacing(4)

        b = QPushButton(scene["name"]); b.setFixedHeight(32)
        b.setCheckable(True); b.setChecked(active)
        self._style_scene_btn(b, active)
        b.clicked.connect(lambda _, i=sid: self._select(i))
        rl.addWidget(b, 1)

        del_b = QPushButton("✕"); del_b.setFixedSize(28, 28)
        del_b.setToolTip("Удалить сцену")
        del_b.setStyleSheet(
            f"QPushButton{{background:#5C1A1A;color:#FF4444;"
            f"border:2px solid #FF4444;border-radius:5px;"
            f"font-size:13px;font-weight:900;padding:0;}}"
            f"QPushButton:hover{{background:#FF4444;color:white;"
            f"border-color:#FF6666;}}")
        del_b.clicked.connect(lambda _, i=sid: self._del_scene(i))
        rl.addWidget(del_b)

        self._btns[sid] = b
        self._rows_map[sid] = row
        self._list_l.insertWidget(self._list_l.count()-1, row)

    def _select(self, sid: int):
        store = get_monitor_store()
        store.set_active_scene(sid)
        for s_id, b in self._btns.items():
            b.setChecked(s_id == sid)
            self._style_scene_btn(b, s_id == sid)
        self.scene_selected.emit(sid)
        get_monitor_engine().switch_scene(sid)

    def _add_scene(self):
        name, ok = QInputDialog.getText(
            self, "Новая сцена", "Название сцены:", text="Сцена")
        if not ok or not name.strip(): return
        sid = get_monitor_store().add_scene(name.strip())
        s   = get_monitor_store().get_scene(sid)
        self._add_btn(s, False)
        self.scene_added.emit(sid)

    def _del_scene(self, sid: int):
        if len(get_monitor_store().scenes()) <= 1:
            QMessageBox.warning(self,"Нельзя","Нужна хотя бы одна сцена."); return
        scene = get_monitor_store().get_scene(sid)
        name  = scene["name"] if scene else "?"
        r = QMessageBox.question(
            self, "Удалить сцену?",
            f"Удалить сцену «{name}» со всеми зонами?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        get_monitor_store().delete_scene(sid)
        # Find and remove the row widget that contains this scene button
        self._btns.pop(sid, None)
        row_w = self._rows_map.pop(sid, None)
        if row_w:
            self._list_l.removeWidget(row_w)
            row_w.deleteLater()
        # Auto-select another scene
        scenes = get_monitor_store().scenes()
        if scenes:
            new_sid = scenes[0]["id"]
            self._select(new_sid)
        self.scene_deleted.emit(sid)

    def _style_scene_btn(self, b: QPushButton, active: bool):
        c = COLORS
        if active:
            b.setStyleSheet(
                f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
                f"border:1px solid {c['accent']};border-radius:6px;text-align:left;"
                f"padding:0 10px;font-size:{FONTS['size_sm']};font-weight:600;}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;color:{c['text_secondary']};"
                f"border:1px solid transparent;border-radius:6px;text-align:left;"
                f"padding:0 10px;font-size:{FONTS['size_sm']};}}"
                f"QPushButton:hover{{background:{c['bg_elevated']};"
                f"color:{c['text_primary']};}}")



# ── Collapsible section widget ────────────────────────────────────────────────
class CollapsibleSection(QWidget):
    """
    Expandable/collapsible section with a header button.
    Content widget is shown/hidden on click.
    """
    def __init__(self, title: str, expanded: bool = True,
                 accent: bool = False, parent=None):
        super().__init__(parent)
        c = COLORS
        self.setStyleSheet("background:transparent;")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header button
        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        col = c['accent'] if accent else c['border_bright']
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background:{c['bg_elevated']};
                color:{c['text_secondary']};
                border:none;
                border-left:3px solid {col};
                border-radius:0px;
                text-align:left;
                padding:5px 10px;
                font-size:{FONTS['size_xs']};
                font-weight:700;
            }}
            QPushButton:hover {{
                background:{c['bg_hover']};
                color:{c['text_primary']};
            }}
        """)
        self._title = title
        self._update_btn(expanded)
        self._btn.toggled.connect(self._on_toggle)
        root.addWidget(self._btn)

        # Content container
        self._body = QWidget()
        self._body.setStyleSheet(
            f"background:{c['bg_card']};border-left:3px solid {col};"
            f"border-bottom:1px solid {c['border']};")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(10, 8, 8, 10)
        self._body_lay.setSpacing(5)
        self._body.setVisible(expanded)
        root.addWidget(self._body)

    def add(self, widget):
        self._body_lay.addWidget(widget)

    def add_layout(self, layout):
        self._body_lay.addLayout(layout)

    def layout_ref(self) -> QVBoxLayout:
        return self._body_lay

    def _on_toggle(self, checked: bool):
        self._body.setVisible(checked)
        self._update_btn(checked)

    def _update_btn(self, expanded: bool):
        arrow = "▾" if expanded else "▸"
        self._btn.setText(f"  {arrow}  {self._title}")

    def set_expanded(self, expanded: bool):
        self._btn.setChecked(expanded)


# ── Zone editor (side panel) ──────────────────────────────────────────────────
class ZoneEditor(QWidget):
    zone_saved = pyqtSignal(dict)   # returns saved zone with id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit_zone  = None
        self._scene_id   = None
        self._rect       = None
        self._ref_b64    = ""
        self._tpl_b64    = ""
        self._search_rect = None
        self._cx_rel     = 0
        self._cy_rel     = 0
        self._r_rel      = 0
        self._build()

    def _build(self):
        c = COLORS
        self.setObjectName("ZoneEditor")
        self.setStyleSheet(
            f"QWidget#ZoneEditor{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-left:2px solid {c['accent']};border-radius:0px;}}"
            f"QLabel{{background:transparent;border:none;}}")
        self.setFixedWidth(520)

        # Outer: just the scroll area filling the widget
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{c['bg_card']};border:none;}}"
            f"QScrollBar:vertical{{background:{c['bg_deep']};width:6px;border-radius:3px;}}"
            f"QScrollBar::handle:vertical{{background:{c['border_bright']};border-radius:3px;"
            f"min-height:20px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}")
        outer.addWidget(scroll)
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner); lay.setContentsMargins(16,16,16,16); lay.setSpacing(8)

        # Header
        self.hdr = QLabel("Новая зона")
        self.hdr.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_lg']};font-weight:700;")
        lay.addWidget(self.hdr)
        lay.addWidget(self._sep())

        # Name
        self._lbl(lay, "Название")
        self.name_e = self._inp("Например: Баф щита")
        lay.addWidget(self.name_e)

        # Zone type
        self._lbl(lay, "Тип зоны")
        self.zone_type_cb = QComboBox()
        self.zone_type_cb.addItems([
            "🎯  Пиксельное сравнение  (статичный элемент)",
            "🔍  Поиск иконки  (смещающийся баф/иконка)",
        ])
        self.zone_type_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.zone_type_cb)
        self.zone_type_cb.currentIndexChanged.connect(self._on_zone_type)
        lay.addWidget(self.zone_type_cb)

        # Region + capture
        self._lbl(lay, "Область / Иконка")
        row1 = QHBoxLayout(); row1.setSpacing(6)
        self.rect_lbl = QLabel("Не выбрана")
        self.rect_lbl.setStyleSheet(
            f"color:{c['text_muted']};background:{c['bg_deep']};"
            f"border:1px solid {c['border']};border-radius:5px;"
            f"padding:4px 8px;font-size:{FONTS['size_xs']};font-family:{FONTS['mono']};")
        self.rect_lbl.setMaximumWidth(240)
        self.shape_cb = QComboBox()
        self.shape_cb.addItems(["▭ Прямоугольник", "⬤ Круг"])
        self.shape_cb.setFixedWidth(130); self.shape_cb.setFixedHeight(28)
        self.shape_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.shape_cb)
        btn_sel = self._btn("⊹ Выделить", self._select_region)
        row1.addWidget(self.shape_cb)
        row1.addWidget(self.rect_lbl,1); row1.addWidget(btn_sel)
        lay.addLayout(row1)

        # Preview + capture btn
        row2 = QHBoxLayout(); row2.setSpacing(8)
        self.thumb = ThumbLabel(120, 68)
        row2.addWidget(self.thumb)
        col_v = QVBoxLayout(); col_v.setSpacing(4)
        self.ref_lbl = QLabel("Эталон не захвачен")
        self.ref_lbl.setWordWrap(True)
        self.ref_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        col_v.addWidget(self.ref_lbl)
        col_v.addStretch()
        btn_cap = self._btn("📷 Захватить эталон", self._capture)
        col_v.addWidget(btn_cap)
        row2.addLayout(col_v,1)
        lay.addLayout(row2)

        # ── Template search fields (shown only for template zone type) ──────
        self.tpl_w = QWidget(); tl = QVBoxLayout(self.tpl_w)
        tl.setContentsMargins(0,4,0,0); tl.setSpacing(4)

        # ═══════════════════════════════════════
        # СЕКЦИЯ 1: Зона поиска
        # ═══════════════════════════════════════
        _sec1 = CollapsibleSection("📐  ЗОНА ПОИСКА  (полоска бафов)", expanded=True)
        tl.addWidget(_sec1)

        sr_row = QHBoxLayout(); sr_row.setSpacing(6)
        self.search_rect_lbl = QLabel("Не выбрана")
        self.search_rect_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};background:{COLORS['bg_deep']};"
            f"border:1px solid {COLORS['border']};border-radius:5px;"
            f"padding:4px 8px;font-size:{FONTS['size_xs']};font-family:{FONTS['mono']};")
        self.search_rect_lbl.setMaximumWidth(240)
        btn_sr = self._btn("⊹ Выбрать", self._select_search_rect)
        sr_row.addWidget(self.search_rect_lbl,1); sr_row.addWidget(btn_sr)
        _sec1.add_layout(sr_row)

        ext_row = QHBoxLayout(); ext_row.setSpacing(8)
        ext_lbl = QLabel("Расширить вниз для цифр:")
        ext_lbl.setFixedHeight(28)
        ext_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        ext_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        self.extend_below_sp = self._make_spin(24, 0, 200, suffix="  пкс", w=80)
        self.extend_below_sp.setToolTip(
            "Увеличивает высоту захвата вниз чтобы захватить цифры под иконками.")
        self.extend_below_sp.valueChanged.connect(
            lambda v: self._ocr_zone_sp.setValue(v)
            if hasattr(self, '_ocr_zone_sp') else None)
        ext_row.addWidget(ext_lbl); ext_row.addWidget(self.extend_below_sp); ext_row.addStretch()
        _sec1.add_layout(ext_row)

        # ═══════════════════════════════════════
        # СЕКЦИЯ 2: Иконка-эталон
        # ═══════════════════════════════════════
        _sec2 = CollapsibleSection("🎯  ИКОНКА БАФА  (маленький эталон)", expanded=True)
        tl.addWidget(_sec2)

        tpl_row = QHBoxLayout(); tpl_row.setSpacing(8)
        self.tpl_thumb = ThumbLabel(64, 36)
        tpl_row.addWidget(self.tpl_thumb)
        tv2 = QVBoxLayout(); tv2.setSpacing(3)
        self.tpl_info_lbl = QLabel("Захватите иконку бафа")
        self.tpl_info_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        btn_cap_tpl = self._btn("📷 Захватить иконку", self._capture_template)
        tv2.addWidget(self.tpl_info_lbl); tv2.addStretch(); tv2.addWidget(btn_cap_tpl)
        tpl_row.addLayout(tv2,1)
        _sec2.add_layout(tpl_row)

        # ═══════════════════════════════════════
        # СЕКЦИЯ 3: Условие и порог
        # ═══════════════════════════════════════
        _sec3 = CollapsibleSection("⚙  УСЛОВИЕ СРАБАТЫВАНИЯ", expanded=True, accent=True)
        tl.addWidget(_sec3)

        cond_lbl = QLabel("Когда:")
        cond_lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        _sec3.add(cond_lbl)
        self.tpl_cond_cb = QComboBox()
        self.tpl_cond_cb.addItems(["Иконка найдена","Иконка не найдена"])
        self.tpl_cond_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.tpl_cond_cb)
        _sec3.add(self.tpl_cond_cb)

        thresh_row = QHBoxLayout(); thresh_row.setSpacing(6)
        self._lbl_h_inline(thresh_row,"Точность совпадения:")
        self.tpl_thresh_sp = _SpinRow(0.72, 0.50, 1.00, suffix="", w_spin=64, double=True, step=0.01)
        thresh_row.addWidget(self.tpl_thresh_sp); thresh_row.addStretch()
        _sec3.add_layout(thresh_row)

        thr_hint = QLabel(
            "⚠  Рекомендуемый диапазон: 0.70–0.85. При 0.99 совпадений почти не будет.")
        thr_hint.setWordWrap(True)
        thr_hint.setStyleSheet(
            f"color:{COLORS['amber']};font-size:{FONTS['size_xs']};"
            f"background:{COLORS['amber_dim']};border:1px solid {COLORS['amber']};"
            f"border-radius:5px;padding:5px 8px;")
        _sec3.add(thr_hint)

        # ═══════════════════════════════════════
        # СЕКЦИЯ 4: Числовое значение (OCR)
        # ═══════════════════════════════════════
        _sec4 = CollapsibleSection("🔢  ЧИСЛОВОЕ ЗНАЧЕНИЕ НА ИКОНКЕ  (OCR)", expanded=False)
        tl.addWidget(_sec4)

        self.match_mode_cb = QComboBox()
        self.match_mode_cb.addItems([
            "Только наличие иконки",
            "Значение < порога",
            "Значение > порога",
            "Значение = порогу",
        ])
        self.match_mode_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.match_mode_cb)
        self.match_mode_cb.currentIndexChanged.connect(self._on_match_mode)
        _sec4.add(self.match_mode_cb)

        self.tpl_val_w = QWidget(); vl = QHBoxLayout(self.tpl_val_w)
        vl.setContentsMargins(0,0,0,0); vl.setSpacing(6)
        self._lbl_h_inline(vl, "Порог:")
        self.value_target_sp = _SpinRow(3, 0, 9999, suffix="", w_spin=64)
        self._lbl_h_inline(vl, "  Позиция цифры:")
        self.val_region_cb = QComboBox()
        _vr_items = [
            ("⬇ ниже иконки  (below)",    "below"),
            ("⬆ выше иконки  (above)",    "above"),
            ("➡ правее иконки (right)",   "right"),
            ("⬅ левее иконки  (left)",    "left"),
            ("🔲 поверх иконки (overlay)", "overlay"),
        ]
        for label, _ in _vr_items:
            self.val_region_cb.addItem(label)
        self.val_region_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.val_region_cb)
        self.val_region_cb.setFixedWidth(200)
        self._vr_values = [v for _, v in _vr_items]
        vl.addWidget(self.value_target_sp); vl.addWidget(self.val_region_cb)
        vl.addStretch()
        _sec4.add(self.tpl_val_w)
        self.tpl_val_w.hide()

        self._vr_hint = QLabel("")
        self._vr_hint.setWordWrap(True)
        self._vr_hint.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
            f"background:{COLORS['bg_deep']};border:1px solid {COLORS['border']};"
            f"border-radius:5px;padding:5px 8px;")
        self._vr_hint.hide()
        _sec4.add(self._vr_hint)
        self.val_region_cb.currentIndexChanged.connect(self._on_val_region)

        # ═══════════════════════════════════════
        # СЕКЦИЯ 5: Сетка иконок
        # ═══════════════════════════════════════
        _sec5 = CollapsibleSection("🔲  СЕТКА ИКОНОК  (игнорирование фона)", expanded=False)
        tl.addWidget(_sec5)

        self.grid_cb = QCheckBox("Использовать сетку  (иконки одного размера с постоянным шагом)")
        self.grid_cb.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-size:{FONTS['size_xs']};")
        self.grid_cb.stateChanged.connect(self._on_grid_toggle)
        _sec5.add(self.grid_cb)

        self.grid_w = QWidget(); gl = QVBoxLayout(self.grid_w)
        gl.setContentsMargins(0,4,0,0); gl.setSpacing(5)

        note_grid = QLabel(
            "Программа будет проверять только ячейки сетки — "
            "фон между иконками игнорируется.")
        note_grid.setWordWrap(True)
        note_grid.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
            f"background:{COLORS['bg_deep']};border:1px solid {COLORS['border']};"
            f"border-radius:5px;padding:6px 8px;")
        gl.addWidget(note_grid)

        from PyQt6.QtWidgets import QGridLayout as _Grid
        grd = _Grid(); grd.setSpacing(6); grd.setContentsMargins(0,0,0,0)

        def _lbl(t):
            l = QLabel(t)
            l.setFixedHeight(28)
            l.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            l.setStyleSheet(
                f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
                f"background:transparent;padding-right:2px;")
            return l

        self.grid_cell_w = self._make_spin(48, 8, 256)
        self.grid_cell_h = self._make_spin(48, 8, 256)
        self.grid_gap_x  = self._make_spin(4,  0, 128)
        self.grid_gap_y  = self._make_spin(0,  0, 128)
        self.grid_off_x  = self._make_spin(0,  0, 512)
        self.grid_off_y  = self._make_spin(0,  0, 256)

        grd.addWidget(_lbl("Ширина ячейки:"), 0, 0)
        grd.addWidget(self.grid_cell_w,       0, 1)
        grd.addWidget(_lbl("Высота:"),        0, 2)
        grd.addWidget(self.grid_cell_h,       0, 3)
        grd.addWidget(_lbl("Промежуток X:"),  1, 0)
        grd.addWidget(self.grid_gap_x,        1, 1)
        grd.addWidget(_lbl("Y:"),             1, 2)
        grd.addWidget(self.grid_gap_y,        1, 3)
        grd.addWidget(_lbl("Сдвиг X:"),       2, 0)
        grd.addWidget(self.grid_off_x,        2, 1)
        grd.addWidget(_lbl("Y:"),             2, 2)
        grd.addWidget(self.grid_off_y,        2, 3)
        grd.setColumnStretch(4, 1)
        gl.addLayout(grd)

        # OCR zone parameters (yellow strip below icons)
        ocr_sep = QLabel("— OCR-зона (жёлтая полоса с цифрами) —")
        ocr_sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ocr_sep.setStyleSheet(
            f"color:#FFD700;font-size:{FONTS['size_xs']};font-weight:700;"
            f"background:{COLORS['bg_deep']};border:1px solid #7A6000;"
            f"border-radius:4px;padding:3px;")
        gl.addWidget(ocr_sep)

        from PyQt6.QtWidgets import QGridLayout as _Grid2
        ocr_grd = _Grid2(); ocr_grd.setSpacing(6); ocr_grd.setContentsMargins(0,0,0,0)

        def _ocr_lbl(t):
            l = QLabel(t); l.setFixedHeight(28)
            l.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            l.setStyleSheet(
                f"color:#FFD700;font-size:{FONTS['size_xs']};"
                f"background:transparent;padding-right:2px;")
            return l

        self._ocr_height_sp = self._make_spin(24, 0, 200, suffix="  пкс", w=80)
        self._ocr_height_sp.setToolTip("Высота OCR-зоны под каждой ячейкой")
        def _ocr_h_changed(v):
            # Sync to extend_below_sp (for saving)
            self.extend_below_sp.setValue(v)
            # Directly update overlay if open (don't rely on chain)
            if self._overlay_alive():
                self._grid_overlay.update_params(extend_below=v)
        self._ocr_height_sp.valueChanged.connect(_ocr_h_changed)

        self._ocr_off_x_sp  = self._make_spin(0, -50, 50, suffix="  пкс", w=80)
        self._ocr_off_x_sp.setToolTip("Горизонтальное смещение OCR-зоны")

        self._ocr_shrink_sp = self._make_spin(0, 0, 40, suffix="  пкс", w=80)
        self._ocr_shrink_sp.setToolTip(
            "Сужение OCR-зоны с каждой стороны (цифры часто уже иконки)")

        self._ocr_off_y_sp  = self._make_spin(0, -30, 30, suffix="  пкс", w=80)
        self._ocr_off_y_sp.setToolTip("Вертикальное смещение OCR-зоны относительно нижней границы ячейки")

        ocr_grd.addWidget(_ocr_lbl("Высота:"),    0, 0)
        ocr_grd.addWidget(self._ocr_height_sp,    0, 1)
        ocr_grd.addWidget(_ocr_lbl("Сдвиг X:"),   0, 2)
        ocr_grd.addWidget(self._ocr_off_x_sp,     0, 3)
        ocr_grd.addWidget(_ocr_lbl("Сдвиг Y:"),   1, 0)
        ocr_grd.addWidget(self._ocr_off_y_sp,     1, 1)
        ocr_grd.addWidget(_ocr_lbl("Сужение:"),   1, 2)
        ocr_grd.addWidget(self._ocr_shrink_sp,    1, 3)
        ocr_grd.setColumnStretch(4, 1)
        gl.addLayout(ocr_grd)

        # Sync extend_below_sp ↔ _ocr_height_sp
        self.extend_below_sp.valueChanged.connect(
            lambda v: self._ocr_height_sp.setValue(v)
            if hasattr(self, '_ocr_height_sp') else None)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        btn_auto = self._btn("⚙  Авто-определить", self._auto_detect_grid)
        self._btn_preview_grid = self._btn("👁  Предпросмотр",
                                           self._preview_grid,
                                           bg=COLORS['bg_elevated'],
                                           fg=COLORS['text_secondary'])
        self._btn_refresh_grid = self._btn("🔄  Обновить",
                                           self._refresh_grid_preview,
                                           bg=COLORS['bg_elevated'],
                                           fg=COLORS['text_secondary'])
        btn_row.addWidget(btn_auto)
        btn_row.addWidget(self._btn_preview_grid)
        btn_row.addWidget(self._btn_refresh_grid)
        btn_row.addStretch()
        gl.addLayout(btn_row)

        self._grid_preview_lbl = QLabel(
            "Нажмите «Предпросмотр» — откроется окно с сеткой поверх экрана")
        self._grid_preview_lbl.setWordWrap(True)
        self._grid_preview_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        self._grid_preview_lbl.hide()
        gl.addWidget(self._grid_preview_lbl)

        _sec5.add(self.grid_w)
        self.grid_w.hide()

        # ═══════════════════════════════════════
        # СЕКЦИЯ 6: Диагностика
        # ═══════════════════════════════════════
        _sec6 = CollapsibleSection("🐛  ДИАГНОСТИКА", expanded=False)
        tl.addWidget(_sec6)

        self.debug_cb = QCheckBox("Сохранять скриншоты захвата в debug_captures/")
        self.debug_cb.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        self.debug_cb.setToolTip(
            "Сохраняет PNG с нарисованными ячейками сетки и найденным совпадением.\n"
            "Папка debug_captures/ создаётся рядом с main.py.")
        _sec6.add(self.debug_cb)

        lay.addWidget(self.tpl_w)
        self.tpl_w.hide()
        # ── end template fields ───────────────────────────────────────────────

        lay.addWidget(self._sep())

        # Priority
        self._lbl(lay, "Приоритет срабатывания")
        self.pri_cb = QComboBox()
        for k,v in PRIORITY_LABELS.items(): self.pri_cb.addItem(v, k)
        self.pri_cb.setCurrentIndex(1)   # default = Normal
        self.pri_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.pri_cb)
        lay.addWidget(self.pri_cb)

        # Parallel flag
        self.parallel_cb = QCheckBox(
            "⚡ Параллельное выполнение (не ждать очереди)")
        self.parallel_cb.setStyleSheet(
            f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        lay.addWidget(self.parallel_cb)

        self.repeat_cb = QCheckBox(
            "🔁 Повторять по кулдауну (не ждать исчезновения иконки)")
        self.repeat_cb.setStyleSheet(
            f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.repeat_cb.setToolTip(
            "Включите если иконка/условие постоянно присутствует\n"
            "и нужно жать кнопку каждые N секунд (кулдаун).\n"
            "Без этой галки — действие срабатывает только при\n"
            "переходе из 'нет совпадения' → 'совпадение'.")
        lay.addWidget(self.repeat_cb)

        lay.addWidget(self._sep())

        # Pixel-mode condition + threshold (hidden in template mode)
        self.pix_cond_w = QWidget(); pl = QVBoxLayout(self.pix_cond_w)
        pl.setContentsMargins(0,0,0,0); pl.setSpacing(6)
        self._lbl_h_to(pl, "Условие срабатывания")
        self.cond_cb = QComboBox()
        self.cond_cb.addItems([
            "Совпадает с эталоном  (match)",
            "Не совпадает с эталоном  (no_match)",
        ])
        self.cond_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.cond_cb)
        pl.addWidget(self.cond_cb)
        thr_row = QHBoxLayout(); thr_row.setSpacing(8)
        self._lbl_h_inline(thr_row, "Порог схожести:")
        self.thr_sp = _SpinRow(0.90, 0.50, 1.00, suffix="", w_spin=64, double=True, step=0.01)
        thr_row.addWidget(self.thr_sp); thr_row.addStretch()
        pl.addLayout(thr_row)
        lay.addWidget(self.pix_cond_w)

        lay.addWidget(self._sep())

        # Action
        self._lbl(lay, "Действие при срабатывании")
        self.act_cb = QComboBox()
        self.act_cb.addItems(["Нажать клавишу/кнопку","Выполнить макрос"])
        self.act_cb.setStyleSheet(self._combo_s())
        self._no_wheel(self.act_cb)
        self.act_cb.currentIndexChanged.connect(self._on_act_type)
        lay.addWidget(self.act_cb)

        # Key row
        self.key_w = QWidget(); kl = QHBoxLayout(self.key_w)
        kl.setContentsMargins(0,0,0,0); kl.setSpacing(6)
        self.key_e = QLineEdit(); self.key_e.setReadOnly(True)
        self.key_e.setPlaceholderText("Нажмите «Назначить»")
        self.key_e.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:5px;padding:4px 8px;"
            f"color:{c['accent_bright']};font-family:{FONTS['mono']};"
            f"font-size:{FONTS['size_sm']};")
        btn_hk = self._btn("🎯 Назначить", self._open_hk)
        kl.addWidget(self.key_e,1); kl.addWidget(btn_hk)
        lay.addWidget(self.key_w)

        # Macro row
        self.mac_w = QWidget(); ml = QHBoxLayout(self.mac_w)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(6)
        self._lbl_h(ml,"Макрос:")
        self.mac_cb = QComboBox(); self.mac_cb.setStyleSheet(self._combo_s())
        self._refresh_macros()
        ml.addWidget(self.mac_cb,1)
        lay.addWidget(self.mac_w)
        self.mac_w.hide()

        # Cooldown
        cool_row = QHBoxLayout(); cool_row.setSpacing(6)
        self._lbl_h(cool_row,"Кулдаун:")
        self.cool_sp = _SpinRow(1000, 100, 60000, suffix=" мс", w_spin=90)
        cool_row.addWidget(self.cool_sp); cool_row.addStretch()
        lay.addLayout(cool_row)

        # Humanization
        hum_row = QHBoxLayout(); hum_row.setSpacing(6)
        self._lbl_h(hum_row,"Гуманизация ±:")
        self.hum_sp = _SpinRow(0, 0, 5000, suffix=" мс", w_spin=90)
        self.hum_sp.setToolTip("Случайное отклонение ± мс от кулдауна")
        hum_row.addWidget(self.hum_sp); hum_row.addStretch()
        lay.addLayout(hum_row)

        lay.addStretch()

        self.save_btn = QPushButton("💾  Сохранить зону")
        self.save_btn.setFixedHeight(38)
        self.save_btn.setStyleSheet(
            f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
            f"border:1px solid {c['accent']};border-radius:7px;"
            f"font-size:{FONTS['size_md']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent']};color:white;}}")
        self.save_btn.clicked.connect(self._save)
        lay.addWidget(self.save_btn)

    # ── Slots ─────────────────────────────────────────────────────────────
    def set_scene(self, sid: int):
        self._scene_id = sid

    def _select_region(self):
        from ui.widgets.region_selector import RegionSelectorOverlay
        mode = "circle" if self.shape_cb.currentIndex() == 1 else "rect"
        self._overlay = RegionSelectorOverlay(mode=mode)
        self._overlay.region_selected.connect(self._on_region)
        self._overlay.circle_selected.connect(self._on_circle)

    def _on_region(self, x, y, w, h):
        self._rect = [x,y,w,h]
        self.rect_lbl.setText(f"{w}×{h}  @  ({x},{y})")
        # For template mode, don't auto-capture reference on region select
        if self.zone_type_cb.currentIndex() == 0:
            QTimer.singleShot(120, self._capture)

    def _on_circle(self, cx, cy, r):
        """Store circle geometry relative to bounding rect."""
        self._cx_rel = r   # center is at (r,r) within bounding rect
        self._cy_rel = r
        self._r_rel  = r

    def _select_search_rect(self):
        """Select the search area (full buff bar) for template mode."""
        from ui.widgets.region_selector import RegionSelectorOverlay
        self._sr_overlay = RegionSelectorOverlay(mode="rect")
        self._sr_overlay.region_selected.connect(self._on_search_rect)

    def _on_search_rect(self, x, y, w, h):
        self._search_rect = [x, y, w, h]
        self.search_rect_lbl.setText(f"{w}×{h}  @  ({x},{y})")

    def _capture_template(self):
        """Capture the small icon template for template matching."""
        if not self._rect:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self,"Нет области","Сначала выделите иконку бафа."); return
        img = capture_region(self._rect)
        if not img: return
        self._tpl_b64 = image_to_b64(img)
        self.tpl_thumb.set_b64(self._tpl_b64)
        self.tpl_info_lbl.setText(f"✓ {img.width}×{img.height}px иконка")
        self.tpl_info_lbl.setStyleSheet(
            f"color:{COLORS['success']};font-size:{FONTS['size_xs']};")

    def _on_zone_type(self, idx: int):
        """Toggle between pixel and template UI sections."""
        is_template = idx == 1
        # pixel fields
        self.thumb.setVisible(not is_template)
        self.ref_lbl.setVisible(not is_template)
        self.pix_cond_w.setVisible(not is_template)
        # template fields
        self.tpl_w.setVisible(is_template)
        if is_template and self.grid_cb.isChecked():
            self.grid_w.show()
        elif not is_template:
            self.grid_w.hide()

    def _on_match_mode(self, idx: int):
        self.tpl_val_w.setVisible(idx > 0)

    def _on_grid_toggle(self, state: int):
        from PyQt6.QtCore import Qt
        self.grid_w.setVisible(state == Qt.CheckState.Checked.value)

    def _auto_detect_grid(self):
        """
        Auto-detect icon grid step from the search_rect image.
        Uses vertical projection of edges to find repeating bright columns (icon borders).
        """
        if not self._search_rect:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Нет области", "Сначала выберите зону поиска.")
            return
        from core.monitor_engine import capture_region
        import numpy as np
        img = capture_region(self._search_rect)
        if img is None:
            return
        arr = np.array(img.convert("L"), dtype=np.float32)
        # Sobel-like horizontal edge detection → find columns with strong edges
        edges = np.abs(np.diff(arr, axis=1)).mean(axis=0)
        # Smooth
        kernel = np.ones(3) / 3
        edges = np.convolve(edges, kernel, mode="same")
        # Find peaks (icon borders)
        from scipy.signal import find_peaks
        try:
            peaks, _ = find_peaks(edges, height=edges.mean() * 1.5, distance=10)
            if len(peaks) >= 2:
                diffs = np.diff(peaks)
                step = int(np.median(diffs))
                # Assume icon = ~80% of step, gap = ~20%
                cell_w = max(8, int(step * 0.80))
                gap_x  = max(0, step - cell_w)
                cell_h = min(img.height, cell_w)
                self.grid_cell_w.setValue(cell_w)
                self.grid_cell_h.setValue(cell_h)
                self.grid_gap_x.setValue(gap_x)
                self.grid_gap_y.setValue(0)
                self.grid_off_x.setValue(int(peaks[0]) if len(peaks) else 0)
                from PyQt6.QtWidgets import QMessageBox
                msg = (f"Найдено {len(peaks)} иконок." + "\n" +
                       f"Ячейка: {cell_w}x{cell_h}пкс  Промежуток: {gap_x}пкс" + "\n" +
                       "Проверьте значения и скорректируйте при необходимости.")
                QMessageBox.information(self, "Авто-определение", msg)
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Авто-определение",
                    "Не удалось определить сетку. Задайте параметры вручную.")
        except ImportError:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "scipy не установлен",
                "Для авто-определения нужен scipy (pip install scipy). Задайте параметры вручную.")

    def _on_val_region(self, idx: int):
        """Show visual hint explaining where OCR will look for the number."""
        _hints = {
            0: ("⬇  BELOW — цифра под иконкой (напр. '105' снизу)\n"
                "Убедитесь что 'Расширить вниз' >= высоты полосы с цифрой"),
            1: ("⬆  ABOVE — цифра над иконкой (таймер сверху)"),
            2: ("➡  RIGHT — цифра справа от иконки"),
            3: ("⬅  LEFT — цифра слева от иконки"),
            4: ("🔲  OVERLAY — цифра поверх иконки (в левом нижнем углу)\n"
                "Подходит когда число нарисовано прямо на иконке"),
        }
        hint = _hints.get(idx, "")
        if hint:
            self._vr_hint.setText(hint)
            self._vr_hint.show()
        else:
            self._vr_hint.hide()

    def _refresh_grid_preview(self):
        """Push current spinbox values into open overlay without reopening."""
        if self._overlay_alive():
            self._grid_overlay.update_params(
                cell_w=self.grid_cell_w.value(),
                cell_h=self.grid_cell_h.value(),
                gap_x=self.grid_gap_x.value(),
                gap_y=self.grid_gap_y.value(),
                off_x=self.grid_off_x.value(),
                off_y=self.grid_off_y.value(),
                extend_below=self.extend_below_sp.value(),
            )
            self._grid_preview_lbl.setText("✓  Предпросмотр обновлён.")
        else:
            self._preview_grid()

    def _hsep_small(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            f"background:{COLORS['border']};max-height:1px;border:none;margin:4px 0;")
        return f

    def _overlay_alive(self) -> bool:
        """Safe check — returns False if C++ object was deleted (WA_DeleteOnClose)."""
        ov = getattr(self, '_grid_overlay', None)
        if ov is None:
            return False
        try:
            return ov.isVisible()
        except RuntimeError:
            self._grid_overlay = None
            return False

    def _preview_grid(self):
        """Show a fullscreen overlay. Closes any existing one first."""
        if not self._search_rect:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Нет области", "Сначала выберите зону поиска бафов.")
            return

        # Close existing overlay safely before creating a new one
        if self._overlay_alive():
            try:
                self._grid_overlay.close()
            except RuntimeError:
                pass
        self._grid_overlay = None

        self._grid_preview_lbl.show()
        self._grid_preview_lbl.setText(
            "Предпросмотр открыт — меняйте цифры, сетка обновится мгновенно. "
            "Enter/двойной клик = применить.  Esc = отмена.")

        ov = GridPreviewOverlay(
            search_rect    = self._search_rect,
            cell_w         = self.grid_cell_w.value(),
            cell_h         = self.grid_cell_h.value(),
            gap_x          = self.grid_gap_x.value(),
            gap_y          = self.grid_gap_y.value(),
            off_x          = self.grid_off_x.value(),
            off_y          = self.grid_off_y.value(),
            extend_below   = self.extend_below_sp.value(),
            ocr_off_x      = getattr(self, '_ocr_off_x_val', 0),
            ocr_shrink     = getattr(self, '_ocr_shrink_val', 0),
            on_apply       = self._apply_grid_from_preview,
        )
        self._grid_overlay = ov

        # Live-sync spinboxes → overlay (guard against deleted C++ object)
        def _safe(fn):
            def _cb(v):
                if self._overlay_alive():
                    try:
                        fn(v)
                    except RuntimeError:
                        self._grid_overlay = None
            return _cb

        self.grid_cell_w.valueChanged.connect(_safe(lambda v: ov.update_params(cell_w=v)))
        self.grid_cell_h.valueChanged.connect(_safe(lambda v: ov.update_params(cell_h=v)))
        self.grid_gap_x.valueChanged.connect( _safe(lambda v: ov.update_params(gap_x=v)))
        self.grid_gap_y.valueChanged.connect( _safe(lambda v: ov.update_params(gap_y=v)))
        self.grid_off_x.valueChanged.connect( _safe(lambda v: ov.update_params(off_x=v)))
        self.grid_off_y.valueChanged.connect( _safe(lambda v: ov.update_params(off_y=v)))
        self.extend_below_sp.valueChanged.connect(_safe(lambda v: ov.update_params(extend_below=v)))
        if hasattr(self, '_ocr_off_x_sp'):
            self._ocr_off_x_sp.valueChanged.connect(_safe(lambda v: ov.update_params(ocr_off_x=v)))
        if hasattr(self, '_ocr_off_y_sp'):
            self._ocr_off_y_sp.valueChanged.connect(_safe(lambda v: ov.update_params(ocr_off_y=v)))
        if hasattr(self, '_ocr_shrink_sp'):
            self._ocr_shrink_sp.valueChanged.connect(_safe(lambda v: ov.update_params(ocr_shrink=v)))

        ov.show()
        ov.activateWindow()
        ov.raise_()

    def _apply_grid_from_preview(self, off_x, off_y, cell_w, cell_h, gap_x, gap_y,
                                  extend_below=None,
                                  ocr_off_x=None, ocr_off_y=None, ocr_shrink=None):
        self.grid_off_x.setValue(off_x)
        self.grid_off_y.setValue(off_y)
        self.grid_cell_w.setValue(cell_w)
        self.grid_cell_h.setValue(cell_h)
        self.grid_gap_x.setValue(gap_x)
        self.grid_gap_y.setValue(gap_y)
        if extend_below is not None:
            self.extend_below_sp.setValue(extend_below)
            if hasattr(self, '_ocr_height_sp'):
                self._ocr_height_sp.setValue(extend_below)
        if ocr_off_x is not None and hasattr(self, '_ocr_off_x_sp'):
            self._ocr_off_x_sp.setValue(ocr_off_x)
        if ocr_off_y is not None and hasattr(self, '_ocr_off_y_sp'):
            self._ocr_off_y_sp.setValue(ocr_off_y)
        if ocr_shrink is not None and hasattr(self, '_ocr_shrink_sp'):
            self._ocr_shrink_sp.setValue(ocr_shrink)
        self._grid_preview_lbl.setText("✓  Параметры сетки и OCR-зоны обновлены.")

    def _capture(self):
        if not self._rect:
            QMessageBox.warning(self,"Нет области","Сначала выделите область."); return
        img = capture_region(self._rect)
        if not img:
            QMessageBox.warning(self,"Ошибка","Не удалось захватить."); return
        self._ref_b64 = image_to_b64(img)
        self.thumb.set_b64(self._ref_b64)
        self.ref_lbl.setText(f"✓ {img.width}×{img.height}px")
        self.ref_lbl.setStyleSheet(
            f"color:{COLORS['success']};font-size:{FONTS['size_xs']};")

    def _on_act_type(self, idx):
        self.key_w.setVisible(idx==0); self.mac_w.setVisible(idx==1)

    def _open_hk(self):
        from ui.hotkey_capture import HotkeyCaptureDialog
        dlg = HotkeyCaptureDialog(current_hotkey=self.key_e.text(), parent=self)
        dlg.hotkey_captured.connect(self.key_e.setText); dlg.exec()

    def _refresh_macros(self):
        from core.macro_store import get_store
        self.mac_cb.clear()
        for m in get_store().all():
            self.mac_cb.addItem(m.get("name","?"), m.get("id"))

    def _save(self):
        if not self._scene_id:
            QMessageBox.warning(self,"Нет сцены","Выберите сцену."); return
        name = self.name_e.text().strip()
        if not name:
            QMessageBox.warning(self,"Ошибка","Введите название зоны."); return
        if not self._rect:
            QMessageBox.warning(self,"Ошибка","Выделите область."); return
        is_tpl = self.zone_type_cb.currentIndex() == 1
        if not is_tpl and not self._ref_b64:
            QMessageBox.warning(self,"Ошибка","Захватите эталон."); return

        is_tpl = self.zone_type_cb.currentIndex() == 1
        atype  = "key" if self.act_cb.currentIndex()==0 else "macro"
        mm_map = ["icon_only","icon_value_lt","icon_value_gt","icon_value_eq"]
        data = {
            "name":            name,
            "zone_type":       "template" if is_tpl else "pixel",
            "shape":           "circle" if self.shape_cb.currentIndex()==1 else "rect",
            "rect":            self._rect,
            "cx_rel":          self._cx_rel,
            "cy_rel":          self._cy_rel,
            "r_rel":           self._r_rel,
            # pixel fields
            "reference":       self._ref_b64,
            "condition":       "match" if self.cond_cb.currentIndex()==0 else "no_match",
            "threshold":       round(self.thr_sp.value(), 2),
            # template fields
            "template":        self._tpl_b64,
            "search_rect":     self._search_rect,
            "match_mode":      mm_map[self.match_mode_cb.currentIndex()],
            "value_target":    self.value_target_sp.value(),
            "value_region":    self._vr_values[self.val_region_cb.currentIndex()],
            "tpl_condition":   "found" if self.tpl_cond_cb.currentIndex()==0 else "not_found",
            "match_thresh":    round(self.tpl_thresh_sp.value(), 2),
            "extend_below_px": self.extend_below_sp.value(),
            "ocr_off_x":       self._ocr_off_x_sp.value() if hasattr(self,"_ocr_off_x_sp") else 0,
            "ocr_off_y":       self._ocr_off_y_sp.value() if hasattr(self,"_ocr_off_y_sp") else 0,
            "ocr_shrink":      self._ocr_shrink_sp.value() if hasattr(self,"_ocr_shrink_sp") else 0,
            "debug_capture":   self.debug_cb.isChecked(),
            "grid": {
                "cell_w":   self.grid_cell_w.value(),
                "cell_h":   self.grid_cell_h.value(),
                "gap_x":    self.grid_gap_x.value(),
                "gap_y":    self.grid_gap_y.value(),
                "offset_x": self.grid_off_x.value(),
                "offset_y": self.grid_off_y.value(),
            } if self.grid_cb.isChecked() else None,
            # shared
            "priority":        self.pri_cb.currentData(),
            "parallel":        self.parallel_cb.isChecked(),
            "repeat_on_cooldown": self.repeat_cb.isChecked(),
            "action_type":     atype,
            "action_key":      self.key_e.text() if atype=="key" else "",
            "action_macro_id": self.mac_cb.currentData() if atype=="macro" else None,
            "cooldown_ms":     self.cool_sp.value(),
            "humanize_ms":     self.hum_sp.value(),
            "active":          False,
        }
        # For template zones use tpl_condition as condition
        if is_tpl:
            data["condition"] = data["tpl_condition"]
        # Validate
        if is_tpl and not self._tpl_b64:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self,"Нет иконки","Захватите иконку бафа."); return
        if is_tpl and not self._search_rect:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self,"Нет зоны поиска","Выберите зону поиска (полоску бафов)."); return
        store = get_monitor_store()
        if self._edit_zone:
            zid = self._edit_zone["id"]
            store.update_zone(self._scene_id, zid, data)
            data["id"] = zid
        else:
            zid = store.add_zone(self._scene_id, data)
            data["id"] = zid
            self._edit_zone = data
        self.zone_saved.emit(data)
        # Remind user to activate zone if it's new
        if not self._edit_zone:
            log.info(f"Zone '{name}' saved — click ▶ in zone row to activate monitoring")
        self.hdr.setText(f"Зона сохранена: {name}")

    def load(self, zone: dict):
        self._edit_zone  = zone
        self._rect       = zone.get("rect")
        self._ref_b64    = zone.get("reference","")
        self._tpl_b64    = zone.get("template","")
        self._search_rect = zone.get("search_rect")
        self._cx_rel     = zone.get("cx_rel", 0)
        self._cy_rel     = zone.get("cy_rel", 0)
        self._r_rel      = zone.get("r_rel",  0)

        self.hdr.setText(f"Редактировать: {zone.get('name','')}")
        self.name_e.setText(zone.get("name",""))

        # Zone type
        ztype = zone.get("zone_type","pixel")
        self.zone_type_cb.setCurrentIndex(1 if ztype=="template" else 0)
        self._on_zone_type(1 if ztype=="template" else 0)

        # Shape
        self.shape_cb.setCurrentIndex(
            1 if zone.get("shape","rect")=="circle" else 0)

        # Region label
        if self._rect:
            r = self._rect; self.rect_lbl.setText(f"{r[2]}×{r[3]}  @  ({r[0]},{r[1]})")

        # Pixel fields
        self.thumb.set_b64(self._ref_b64)
        if self._ref_b64:
            self.ref_lbl.setText("✓ Эталон загружен")
            self.ref_lbl.setStyleSheet(
                f"color:{COLORS['success']};font-size:{FONTS['size_xs']};")
        self.cond_cb.setCurrentIndex(
            0 if zone.get("condition","match")=="match" else 1)
        self.thr_sp.setValue(zone.get("threshold",0.90))

        # Template fields
        self.tpl_thumb.set_b64(self._tpl_b64)
        if self._tpl_b64:
            self.tpl_info_lbl.setText("✓ Иконка загружена")
            self.tpl_info_lbl.setStyleSheet(
                f"color:{COLORS['success']};font-size:{FONTS['size_xs']};")
        if self._search_rect:
            sr = self._search_rect
            self.search_rect_lbl.setText(f"{sr[2]}×{sr[3]}  @  ({sr[0]},{sr[1]})")
        mm_map = {"icon_only":0,"icon_value_lt":1,"icon_value_gt":2,"icon_value_eq":3}
        self.match_mode_cb.setCurrentIndex(
            mm_map.get(zone.get("match_mode","icon_only"), 0))
        self._on_match_mode(self.match_mode_cb.currentIndex())
        self.value_target_sp.setValue(zone.get("value_target",3))
        vr = zone.get("value_region","below")
        vr_idx = self._vr_values.index(vr) if vr in self._vr_values else 0
        self.val_region_cb.setCurrentIndex(vr_idx)
        self._on_val_region(vr_idx)
        tpl_cond = zone.get("tpl_condition","found")
        self.tpl_cond_cb.setCurrentIndex(0 if tpl_cond=="found" else 1)
        self.tpl_thresh_sp.setValue(zone.get("match_thresh",0.75))
        self.extend_below_sp.setValue(zone.get("extend_below_px", 24))
        if hasattr(self, "_ocr_off_x_sp"):
            self._ocr_off_x_sp.setValue(zone.get("ocr_off_x", 0))
        if hasattr(self, "_ocr_off_y_sp"):
            self._ocr_off_y_sp.setValue(zone.get("ocr_off_y", 0))
        if hasattr(self, "_ocr_shrink_sp"):
            self._ocr_shrink_sp.setValue(zone.get("ocr_shrink", 0))
        self.debug_cb.setChecked(zone.get("debug_capture", False))
        # Grid
        grid = zone.get("grid")
        self.grid_cb.setChecked(bool(grid))
        self._on_grid_toggle(2 if grid else 0)
        if grid:
            self.grid_cell_w.setValue(grid.get("cell_w", 48))
            self.grid_cell_h.setValue(grid.get("cell_h", 48))
            self.grid_gap_x.setValue(grid.get("gap_x", 4))
            self.grid_gap_y.setValue(grid.get("gap_y", 0))
            self.grid_off_x.setValue(grid.get("offset_x", 0))
            self.grid_off_y.setValue(grid.get("offset_y", 0))

        # Shared
        pri = zone.get("priority",2)
        self.pri_cb.setCurrentIndex(pri-1)
        self.parallel_cb.setChecked(zone.get("parallel",False))
        self.repeat_cb.setChecked(zone.get("repeat_on_cooldown",False))
        atype = zone.get("action_type","key")
        self.act_cb.setCurrentIndex(0 if atype=="key" else 1)
        self.key_e.setText(zone.get("action_key",""))
        self._refresh_macros()
        self.cool_sp.setValue(zone.get("cooldown_ms",1000))
        self.hum_sp.setValue(zone.get("humanize_ms",0))

    def clear(self):
        self._edit_zone = None; self._rect = None
        self._ref_b64 = ""; self._tpl_b64 = ""
        self._search_rect = None
        self._cx_rel = self._cy_rel = self._r_rel = 0
        self.hdr.setText("Новая зона")
        self.name_e.clear(); self.rect_lbl.setText("Не выбрана")
        self.thumb.set_b64(""); self.key_e.clear()
        self.thr_sp.setValue(0.90); self.cool_sp.setValue(1000); self.hum_sp.setValue(0)
        self.cond_cb.setCurrentIndex(0); self.act_cb.setCurrentIndex(0)
        self.pri_cb.setCurrentIndex(1); self.parallel_cb.setChecked(False)
        self.ref_lbl.setText("Эталон не захвачен")
        self.ref_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        # template fields
        self.zone_type_cb.setCurrentIndex(0); self._on_zone_type(0)
        self.shape_cb.setCurrentIndex(0)
        self.tpl_thumb.set_b64("")
        self.tpl_info_lbl.setText("Захватите иконку бафа")
        self.tpl_info_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        self.search_rect_lbl.setText("Не выбрана")
        self.match_mode_cb.setCurrentIndex(0); self._on_match_mode(0)
        self.tpl_thresh_sp.setValue(0.75)
        self.tpl_cond_cb.setCurrentIndex(0)
        self.extend_below_sp.setValue(24)
        self.debug_cb.setChecked(False)
        self.grid_cb.setChecked(False); self.grid_w.hide()
        self.grid_cell_w.setValue(48); self.grid_cell_h.setValue(48)
        self.grid_gap_x.setValue(4);   self.grid_gap_y.setValue(0)
        self.grid_off_x.setValue(0);   self.grid_off_y.setValue(0)

    # ── Style helpers ─────────────────────────────────────────────────────
    def _sep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{COLORS['border']};max-height:1px;border:none;")
        return f

    def _lbl(self, lay, t):
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_sm']};font-weight:600;")
        lay.addWidget(l)

    def _lbl_h(self, lay, t):
        l = QLabel(t)
        l.setStyleSheet(f"color:{COLORS['text_muted']};font-size:{FONTS['size_sm']};")
        lay.addWidget(l)

    def _lbl_h_to(self, lay, t):
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
        lay.addWidget(l)

    def _lbl_h_inline(self, lay, t):
        l = QLabel(t)
        l.setFixedHeight(28)
        l.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        l.setStyleSheet(f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        lay.addWidget(l, 0, Qt.AlignmentFlag.AlignVCenter)

    def _inp(self, ph=""):
        c = COLORS; e = QLineEdit(); e.setPlaceholderText(ph)
        e.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:5px 10px;color:{c['text_primary']};"
            f"font-size:{FONTS['size_md']};"); return e

    def _btn(self, t, fn, bg=None, fg=None):
        c = COLORS
        bg = bg or c['bg_elevated']
        fg = fg or c['text_secondary']
        b = QPushButton(t); b.setFixedHeight(28)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};"
            f"border:1px solid {c['border_bright']};border-radius:5px;"
            f"font-size:{FONTS['size_xs']};padding:0 8px;}}"
            f"QPushButton:hover{{background:{c['bg_hover']};color:{c['accent_bright']};"
            f"border-color:{c['accent']};}}")
        b.clicked.connect(fn); return b

    def _no_wheel(self, w):
        """Block scroll wheel on widget so page scroll doesn't change values."""
        w.installEventFilter(_no_scroll)
        w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return w

    def _make_spin(self, val, lo, hi, suffix="  пкс", w=72, double=False, step=1):
        """Return _SpinRow: [−] spinbox [+] with visible white +/- buttons."""
        return _SpinRow(val=val, lo=lo, hi=hi, suffix=suffix,
                        w_spin=w, double=double, step=step)

    def _combo_s(self):
        c = COLORS
        return (f"QComboBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
                f"border:1px solid {c['border_bright']};border-radius:5px;"
                f"padding:3px 8px;font-size:{FONTS['size_sm']};}}"
                f"QComboBox:hover{{border-color:{c['accent']};}}"
                f"QComboBox QAbstractItemView{{background:{c['bg_elevated']};"
                f"color:{c['text_primary']};border:1px solid {c['accent']};"
                f"selection-background-color:{c['accent_dim']};}}")

    def _spin_s(self):
        c = COLORS
        # Use default Qt arrows (always visible) with custom colors
        # +/- text is rendered separately in _make_spin via QLabel overlays
        return (
            f"QSpinBox,QDoubleSpinBox{{background:{c['bg_panel']};"
            f"color:{c['text_primary']};border:1px solid {c['border']};"
            f"border-radius:5px;padding:2px 4px 2px 6px;font-size:{FONTS['size_sm']};}}"
            f"QSpinBox:hover,QDoubleSpinBox:hover{{border-color:{c['accent']};}}"
            f"QSpinBox::up-button,QDoubleSpinBox::up-button{{"
            f"background:{c['bg_elevated']};border-left:1px solid {c['border']};"
            f"border-bottom:1px solid {c['border']};width:22px;"
            f"subcontrol-origin:border;subcontrol-position:top right;}}"
            f"QSpinBox::up-arrow,QDoubleSpinBox::up-arrow{{"
            f"color:white;width:22px;height:13px;}}"
            f"QSpinBox::down-button,QDoubleSpinBox::down-button{{"
            f"background:{c['bg_elevated']};border-left:1px solid {c['border']};"
            f"border-top:1px solid {c['border']};width:22px;"
            f"subcontrol-origin:border;subcontrol-position:bottom right;}}"
            f"QSpinBox::down-arrow,QDoubleSpinBox::down-arrow{{"
            f"color:white;width:22px;height:13px;}}"
        )




# ── Main Monitor Page ─────────────────────────────────────────────────────────
class MonitorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[int, ZoneRow] = {}   # zid → ZoneRow
        self._cur_scene: int | None = None
        self._build()
        self._ensure_default_scene()
        self._load_scene(get_monitor_store().active_scene_id())
        self._connect_signals()

    def _build(self):
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Top bar
        bar = QWidget(); bar.setFixedHeight(60)
        bar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(20,0,20,0); bl.setSpacing(10)
        tv = QVBoxLayout(); tv.setSpacing(1)
        t  = QLabel("Мониторинг экрана")
        t.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;background:transparent;")
        s  = QLabel("Автоматические действия при изменении состояния игрового интерфейса")
        s.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};background:transparent;")
        tv.addWidget(t); tv.addWidget(s); bl.addLayout(tv); bl.addStretch()

        self._lbl_h(bl,"fps:")
        self.fps_sp = QSpinBox(); self.fps_sp.setRange(1,30); self.fps_sp.setValue(10)
        self.fps_sp.setFixedWidth(64); self.fps_sp.setFixedHeight(30)
        self.fps_sp.setStyleSheet(
            f"QSpinBox{{background:{c['bg_elevated']};color:{c['text_primary']};"
            f"border:1px solid {c['border']};border-radius:5px;padding:2px 4px;"
            f"font-size:{FONTS['size_sm']};}}"
            f"QSpinBox::up-button,QSpinBox::down-button{{"
            f"background:{c['bg_panel']};border:none;width:14px;}}")
        bl.addWidget(self.fps_sp)

        self.eng_btn = QPushButton("▶  Запустить мониторинг")
        self.eng_btn.setFixedHeight(34)
        self.eng_btn.setStyleSheet(self._green_btn())
        self.eng_btn.clicked.connect(self._toggle_engine)
        bl.addWidget(self.eng_btn)

        self.new_zone_btn = QPushButton("＋ Зона")
        self.new_zone_btn.setFixedHeight(34)
        self.new_zone_btn.setStyleSheet(
            f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
            f"border:1px solid {c['accent']};border-radius:6px;padding:0 14px;"
            f"font-size:{FONTS['size_sm']};font-weight:600;}}"
            f"QPushButton:hover{{background:{c['accent']};color:white;}}")
        self.new_zone_btn.clicked.connect(self._new_zone)
        bl.addWidget(self.new_zone_btn)
        root.addWidget(bar)

        # Main area: scene panel | zone list | editor
        main = QWidget(); ml = QHBoxLayout(main)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)

        # Scene sidebar
        self.scene_panel = ScenePanel()
        self.scene_panel.scene_selected.connect(self._load_scene)
        self.scene_panel.scene_added.connect(self._load_scene)
        self.scene_panel.scene_deleted.connect(self._on_scene_deleted)
        ml.addWidget(self.scene_panel)

        # Zone list (scrollable, compact rows)
        zone_w = QWidget(); zone_w.setStyleSheet("background:transparent;")
        zl = QVBoxLayout(zone_w); zl.setContentsMargins(16,16,16,16); zl.setSpacing(6)

        zh = QHBoxLayout()
        self.zone_hdr = QLabel("ЗОНЫ")
        self.zone_hdr.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.5px;background:transparent;")
        self.zone_count_lbl = QLabel("0 зон")
        self.zone_count_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        zh.addWidget(self.zone_hdr); zh.addStretch(); zh.addWidget(self.zone_count_lbl)
        zl.addLayout(zh)

        # Priority legend
        leg = QHBoxLayout(); leg.setSpacing(12)
        for pri, label in PRIORITY_LABELS.items():
            col = PRIORITY_COLORS[pri]
            ll  = QLabel(f"● {label}")
            ll.setStyleSheet(
                f"color:{col};font-size:{FONTS['size_xs']};background:transparent;")
            leg.addWidget(ll)
        leg.addStretch()
        leg_note = QLabel("⚡ = параллельное выполнение")
        leg_note.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        leg.addWidget(leg_note)
        zl.addLayout(leg)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;border:none;")
        self.zone_inner = QWidget(); self.zone_inner.setStyleSheet("background:transparent;")
        self.zone_lay   = QVBoxLayout(self.zone_inner)
        self.zone_lay.setContentsMargins(0,0,0,0); self.zone_lay.setSpacing(6)
        self.zone_lay.addStretch()
        scroll.setWidget(self.zone_inner); zl.addWidget(scroll,1)
        ml.addWidget(zone_w,1)

        # Editor panel (right)
        self.editor = ZoneEditor()
        self.editor.zone_saved.connect(self._on_zone_saved)
        ml.addWidget(self.editor)

        root.addWidget(main,1)

    def _ensure_default_scene(self):
        store = get_monitor_store()
        if not store.scenes():
            store.add_scene("Сцена 1")

    def _load_scene(self, sid: int):
        if sid is None: return
        if sid == self._cur_scene: return   # already showing this scene (bug 1 fix)
        self._cur_scene = sid
        self.editor.set_scene(sid)

        # Clear zone list
        while self.zone_lay.count() > 1:
            item = self.zone_lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows.clear()

        scene = get_monitor_store().get_scene(sid)
        name  = scene["name"] if scene else "—"
        self.zone_hdr.setText(f"ЗОНЫ — {name.upper()}")

        zones = get_monitor_store().zones_for(sid)
        for zone in sorted(zones, key=lambda z: z.get("priority",2)):
            self._add_row(zone)
        self._update_count()

    def _on_scene_deleted(self, sid: int):
        new_active = get_monitor_store().active_scene_id()
        if new_active: self._load_scene(new_active)
        else: self._cur_scene = None; self._clear_rows()

    def _add_row(self, zone: dict):
        row = ZoneRow(zone)
        row.edit_clicked.connect(lambda z: self.editor.load(z))
        row.delete_clicked.connect(self._del_zone)
        row.toggled.connect(self._on_toggled)
        row.priority_changed.connect(self._on_priority_changed)
        # Insert before stretch, sorted by priority
        pri = zone.get("priority",2)
        insert_at = 0
        for i in range(self.zone_lay.count()-1):
            item = self.zone_lay.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, ZoneRow) and w.zone.get("priority",2) <= pri:
                    insert_at = i+1
        self.zone_lay.insertWidget(insert_at, row)
        self._rows[zone["id"]] = row
        self._update_count()

    def _new_zone(self):
        if not self._cur_scene:
            QMessageBox.warning(self,"Нет сцены","Выберите или создайте сцену."); return
        self.editor.clear(); self.editor.set_scene(self._cur_scene)

    def _on_zone_saved(self, zone: dict):
        zid = zone["id"]
        if zid in self._rows:
            self._rows[zid].refresh(zone)
        else:
            self._add_row(zone)

    def _del_zone(self, zone: dict):
        zid = zone.get("id")
        if not zid: return
        r = QMessageBox.question(self,"Удалить зону?",
            f"Удалить зону «{zone.get('name','?')}»?")
        if r != QMessageBox.StandardButton.Yes: return
        get_monitor_store().delete_zone(self._cur_scene, zid)
        row = self._rows.pop(zid, None)
        if row: self.zone_lay.removeWidget(row); row.deleteLater()
        self._update_count()

    def _on_toggled(self, zone: dict, active: bool):
        if self._cur_scene:
            get_monitor_store().update_zone(
                self._cur_scene, zone["id"], {"active": active})

    def _on_priority_changed(self, zone: dict, pri: int):
        if self._cur_scene:
            get_monitor_store().update_zone(
                self._cur_scene, zone["id"], {"priority": pri})

    def _update_count(self):
        n = self.zone_lay.count() - 1   # subtract stretch
        self.zone_count_lbl.setText(f"{n} зон")

    def _clear_rows(self):
        while self.zone_lay.count() > 1:
            item = self.zone_lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows.clear()

    def _connect_signals(self):
        monitor_signals.zone_state.connect(self._on_zone_state)
        monitor_signals.zone_triggered.connect(self._on_triggered)
        monitor_signals.scene_changed.connect(self._load_scene)

    def _on_zone_state(self, zid: int, state: str):
        row = self._rows.get(zid)
        if row: row.led.set_state(state)

    def _on_triggered(self, zid: int, name: str, sim: float):
        log.info(f"UI: zone '{name}' triggered sim={sim:.2f}")

    def _toggle_engine(self):
        eng = get_monitor_engine()
        c   = COLORS
        if eng.is_running():
            eng.stop()
            self.eng_btn.setText("▶  Запустить мониторинг")
            self.eng_btn.setStyleSheet(self._green_btn())
        else:
            eng.start(fps=self.fps_sp.value())
            self.eng_btn.setText("⏹  Остановить мониторинг")
            self.eng_btn.setStyleSheet(
                f"QPushButton{{background:{c['danger_dim']};color:{c['danger']};"
                f"border:2px solid {c['danger']};border-radius:6px;padding:0 14px;"
                f"font-size:{FONTS['size_sm']};font-weight:700;}}"
                f"QPushButton:hover{{background:{c['danger']};color:white;}}")

    def _green_btn(self):
        c = COLORS
        return (f"QPushButton{{background:{c['success_dim']};color:{c['success']};"
                f"border:1px solid {c['success']};border-radius:6px;padding:0 14px;"
                f"font-size:{FONTS['size_sm']};font-weight:600;}}"
                f"QPushButton:hover{{background:{c['success']};color:white;}}")

    def _lbl_h(self, lay, t):
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_sm']};"
            f"background:transparent;")
        lay.addWidget(l)


# ═══════════════════════════════════════════════════════════════════════════════
# Grid Preview Overlay
# ═══════════════════════════════════════════════════════════════════════════════
class GridPreviewOverlay(QWidget):
    """
    Fullscreen transparent overlay that draws the icon grid over the buff bar.
    User can drag the grid offset with mouse and click Apply to save back.

    Controls:
      Drag   — move grid offset (off_x / off_y)
      Scroll — adjust cell_w (+ Shift → cell_h)
      Ctrl+Scroll — adjust gap_x (+ Shift → gap_y)
      Esc / Right-click — close without saving
      Enter / Double-click — apply and close
    """

    def __init__(self, search_rect, cell_w, cell_h, gap_x, gap_y,
                 off_x, off_y, extend_below=0,
                 ocr_off_x=0, ocr_off_y=0, ocr_shrink=0,
                 on_apply=None, parent=None):
        super().__init__(parent)
        self._sr       = search_rect
        self._cw       = cell_w
        self._ch       = cell_h
        self._gx       = gap_x
        self._gy       = gap_y
        self._ox       = off_x
        self._oy       = off_y
        self._eb       = extend_below
        self._ocr_ox   = ocr_off_x
        self._ocr_oy   = ocr_off_y
        self._ocr_sk   = ocr_shrink
        self._on_apply = on_apply
        self._drag_start = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMouseTracking(True)

        # Cover all screens
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QRect
        total = QRect()
        for screen in QApplication.screens():
            total = total.united(screen.geometry())
        self.setGeometry(total)
        self.showFullScreen()

    # ── Input ─────────────────────────────────────────────────────────────────
    def keyPressEvent(self, e):
        from PyQt6.QtCore import Qt as QtC
        if e.key() == QtC.Key.Key_Escape:
            self.close()
        elif e.key() in (QtC.Key.Key_Return, QtC.Key.Key_Enter):
            self._apply_and_close()
        # Arrow keys for fine tuning offset
        elif e.key() == QtC.Key.Key_Left:  self._ox = max(0, self._ox - 1); self.update()
        elif e.key() == QtC.Key.Key_Right: self._ox += 1; self.update()
        elif e.key() == QtC.Key.Key_Up:    self._oy = max(0, self._oy - 1); self.update()
        elif e.key() == QtC.Key.Key_Down:  self._oy += 1; self.update()

    def mousePressEvent(self, e):
        from PyQt6.QtCore import Qt as QtC
        if e.button() == QtC.MouseButton.RightButton:
            self.close()
        elif e.button() == QtC.MouseButton.LeftButton:
            self._drag_start = e.pos()

    def mouseDoubleClickEvent(self, e):
        self._apply_and_close()

    def mouseMoveEvent(self, e):
        if self._drag_start is not None:
            dx = e.pos().x() - self._drag_start.x()
            dy = e.pos().y() - self._drag_start.y()
            self._ox = max(0, self._ox + dx)
            self._oy = max(0, self._oy + dy)
            self._drag_start = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag_start = None

    def wheelEvent(self, e):
        from PyQt6.QtCore import Qt as QtC
        delta = 1 if e.angleDelta().y() > 0 else -1
        mods  = e.modifiers()
        if mods & QtC.KeyboardModifier.ControlModifier:
            if mods & QtC.KeyboardModifier.ShiftModifier:
                self._gy = max(0, self._gy + delta)
            else:
                self._gx = max(0, self._gx + delta)
        elif mods & QtC.KeyboardModifier.ShiftModifier:
            self._ch = max(8, self._ch + delta)
        elif mods & QtC.KeyboardModifier.AltModifier:
            self._eb = max(0, self._eb + delta * 2)   # Alt+scroll = OCR zone height
        else:
            self._cw = max(8, self._cw + delta)
        self.update()

    # ── Draw ──────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Dark overlay everywhere outside the search rect
        sx, sy, sw, sh = self._sr
        p.fillRect(0, 0, W, H, QColor(0, 0, 0, 140))
        # Clear search rect
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(sx, sy, sw, sh, QColor(0,0,0,0))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Search rect border
        p.setPen(QPen(QColor("#3D8EF0"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(sx, sy, sw, sh)

        # Grid cells
        step_x = self._cw + self._gx
        step_y = self._ch + self._gy
        cell_pen  = QPen(QColor(0x3D, 0xF0, 0x8E, 200), 1)
        fill_col  = QColor(0x3D, 0xF0, 0x8E, 30)
        label_pen = QPen(QColor(0xFF, 0xFF, 0xFF, 200))
        f = QFont("Segoe UI", 8); p.setFont(f)
        fm = QFontMetrics(f)

        cell_idx = 0
        x = sx + self._ox
        while x < sx + sw:
            y = sy + self._oy
            while y < sy + sh:
                cx2 = min(x + self._cw, sx + sw)
                cy2 = min(y + self._ch, sy + sh)
                if cx2 > x and cy2 > y:
                    p.setPen(cell_pen); p.setBrush(fill_col)
                    p.drawRect(x, y, cx2 - x, cy2 - y)
                    # OCR zone below cell — bright yellow, respects shrink/offset
                    if self._eb > 0:
                        sk     = max(0, self._ocr_sk)
                        ocr_x1 = x + sk + self._ocr_ox
                        ocr_x2 = cx2 - sk + self._ocr_ox
                        ocr_y1 = y + self._ch + self._ocr_oy
                        ocr_y2 = min(sy + sh, ocr_y1 + self._eb)
                        if ocr_x2 > ocr_x1 and ocr_y2 > ocr_y1 + 2:
                            # Bright fill
                            p.setPen(QPen(QColor(255, 230, 0), 2,
                                          Qt.PenStyle.SolidLine))
                            p.setBrush(QColor(255, 230, 0, 130))
                            p.drawRect(ocr_x1, ocr_y1,
                                       ocr_x2 - ocr_x1, ocr_y2 - ocr_y1)
                            # Label on first cell only
                            if cell_idx == 0:
                                p.setPen(QColor(0, 0, 0))
                                p.drawText(ocr_x1 + 2, ocr_y2 - 2,
                                           f"OCR h={self._eb} sk={sk}")
                    p.setPen(label_pen)
                    p.drawText(x + 3, y + 13, str(cell_idx + 1))
                    cell_idx += 1
                y += step_y if step_y > 0 else self._ch + 1
                if step_y <= 0: break
            x += step_x if step_x > 0 else self._cw + 1
            if step_x <= 0: break

        # HUD — current values + controls hint
        self._draw_hud(p, cell_idx)

    def _draw_hud(self, p, cell_count):
        from PyQt6.QtGui import QFont, QColor, QPen
        f = QFont("Segoe UI", 10); p.setFont(f)
        sx, sy = self._sr[0], self._sr[1]

        lines = [
            (f"Ячейки: {self._cw}x{self._ch}  Пром: {self._gx}/{self._gy}"
             f"  Сдвиг: {self._ox}/{self._oy}  Ячеек: {cell_count}"),
            (f"OCR: h={self._eb}  смX={self._ocr_ox}  смY={self._ocr_oy}  суж={self._ocr_sk}"),
            ("Мышь — сдвиг сетки | Scroll — ширина | Shift — высота"
             " | Ctrl — промежуток | Alt — OCR-высота | Enter — применить | Esc — отмена"),
        ]
        pad = 8
        bw  = self.width() - pad * 2
        bh  = len(lines) * 22 + pad * 2
        by  = max(0, sy - bh - 6)
        if by < 4: by = sy + self._sr[3] + 6

        p.fillRect(pad, by, bw, bh, QColor(0x0D, 0x11, 0x1E, 220))
        p.setPen(QPen(QColor("#2A3555")))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(pad, by, bw, bh)

        p.setPen(QColor(0xC0, 0xD8, 0xFF))
        for i, line in enumerate(lines):
            p.drawText(pad + 10, by + pad + 14 + i * 22, line)

        # Apply button hint
        p.setPen(QColor(0x2E, 0xCC, 0x71))
        p.drawText(pad + 10, by + bh - 4, "[ Enter / Двойной клик = Применить ]")

    # ── Apply ─────────────────────────────────────────────────────────────────
    def update_params(self, cell_w=None, cell_h=None,
                      gap_x=None, gap_y=None,
                      off_x=None, off_y=None, extend_below=None,
                      ocr_off_x=None, ocr_off_y=None, ocr_shrink=None):
        if cell_w       is not None: self._cw     = int(cell_w)
        if cell_h       is not None: self._ch     = int(cell_h)
        if gap_x        is not None: self._gx     = int(gap_x)
        if gap_y        is not None: self._gy     = int(gap_y)
        if off_x        is not None: self._ox     = int(off_x)
        if off_y        is not None: self._oy     = int(off_y)
        if extend_below is not None: self._eb     = int(extend_below)
        if ocr_off_x    is not None: self._ocr_ox = int(ocr_off_x)
        if ocr_off_y    is not None: self._ocr_oy = int(ocr_off_y)
        if ocr_shrink   is not None: self._ocr_sk = int(ocr_shrink)
        self.update()

    def _apply_and_close(self):
        if self._on_apply:
            self._on_apply(
                int(self._ox), int(self._oy),
                int(self._cw), int(self._ch),
                int(self._gx), int(self._gy),
                int(self._eb),
                int(self._ocr_ox), int(self._ocr_oy), int(self._ocr_sk),
            )
        self.close()
