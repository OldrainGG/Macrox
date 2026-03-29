"""
MacroX — Журнал (Log Page)
- Font scale selector (5 levels, persisted)
- Resizable stats panel (splitter)
- Smart time formatting (ms → s → m → h)
- Live step/delay counters
"""
import time, logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QSplitter, QCheckBox,
    QButtonGroup, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (QPainter, QColor, QLinearGradient,
                          QBrush, QPainterPath, QPen)
from ui.theme import COLORS, FONTS
from core.journal import get_journal, JournalEntry
from core.font_scale import get_journal_font, get_global_font, fmt_duration, LEVELS

log = logging.getLogger(__name__)

EVENT_ICONS = {
    "started": ("▶", "#2ECC71"),
    "stopped": ("⏹", "#5AA3FF"),
    "step":    ("·", "#4A5068"),
    "error":   ("⚠", "#E74C3C"),
}


# ── Sparkline ─────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._values: list[int] = []

    def push(self, v: int):
        self._values.append(v)
        if len(self._values) > 120: self._values.pop(0)
        self.update()

    def clear(self): self._values.clear(); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(COLORS['bg_deep']))
        if len(self._values) < 2:
            p.setPen(QColor(COLORS['text_muted']))
            p.drawText(0, 0, W, H, Qt.AlignmentFlag.AlignCenter, "—")
            return
        mn, mx = min(self._values), max(self._values)
        rng = (mx - mn) or 1; n = len(self._values); pad = 4

        def xy(i):
            return (int(i/(n-1)*W), H-pad-int((self._values[i]-mn)/rng*(H-2*pad)))

        path = QPainterPath()
        path.moveTo(xy(0)[0], H); path.lineTo(*xy(0))
        for i in range(1, n): path.lineTo(*xy(i))
        path.lineTo(xy(n-1)[0], H); path.closeSubpath()
        g = QLinearGradient(0,0,0,H)
        g.setColorAt(0, QColor(COLORS['accent_dim'])); g.setColorAt(1, QColor(0,0,0,0))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(COLORS['accent']), 1.5))
        for i in range(n-1): p.drawLine(*xy(i), *xy(i+1))
        avg = sum(self._values)//len(self._values)
        ay  = H-pad-int((avg-mn)/rng*(H-2*pad))
        p.setPen(QPen(QColor(COLORS['amber']), 1, Qt.PenStyle.DashLine))
        p.drawLine(0, ay, W, ay)


# ── Bar chart ─────────────────────────────────────────────────────────────────
class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._data: list[tuple] = []

    def set_data(self, data: list):
        self._data = sorted(data, key=lambda x: x[1], reverse=True)[:8]; self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QFont, QFontMetrics
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(COLORS['bg_deep']))
        if not self._data:
            p.setPen(QColor(COLORS['text_muted']))
            p.drawText(0,0,W,H,Qt.AlignmentFlag.AlignCenter,"Нет данных"); return
        fs = get_journal_font()
        f = QFont(FONTS['ui']); f.setPixelSize(fs.pt('xs')); p.setFont(f)
        fm = QFontMetrics(f)
        max_v   = max(v for _,v in self._data) or 1
        n       = len(self._data)
        pad_l   = max(fm.horizontalAdvance(nm) for nm,_ in self._data)+10
        pad_r   = 36; bar_area = W-pad_l-pad_r
        row_h   = H//n; bar_h = max(6, row_h-8)
        for i,(name,val) in enumerate(self._data):
            y = i*row_h+(row_h-bar_h)//2
            p.setPen(QColor(COLORS['text_secondary']))
            p.drawText(0,y,pad_l-6,bar_h,
                       Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,name)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(COLORS['bg_elevated']))
            p.drawRoundedRect(pad_l,y,bar_area,bar_h,3,3)
            fill = int(bar_area*val/max_v)
            if fill > 0:
                g = QLinearGradient(pad_l,0,pad_l+fill,0)
                g.setColorAt(0,QColor(COLORS['accent_dim'])); g.setColorAt(1,QColor(COLORS['accent']))
                p.setBrush(QBrush(g)); p.drawRoundedRect(pad_l,y,fill,bar_h,3,3)
            p.setPen(QColor(COLORS['accent_bright']))
            p.drawText(pad_l+fill+4,y,pad_r,bar_h,
                       Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,str(val))


# ── Stat card ─────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, icon, title, parent=None):
        super().__init__(parent)
        c = COLORS
        self.setFixedHeight(72)
        self.setStyleSheet(
            f"QFrame{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:8px;}} QLabel{{background:transparent;border:none;}}")
        lay = QVBoxLayout(self); lay.setContentsMargins(12,8,12,8); lay.setSpacing(2)
        hdr = QHBoxLayout()
        ic  = QLabel(icon); ic.setStyleSheet(f"color:{c['text_muted']};font-size:12px;")
        ttl = QLabel(title)
        ttl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};font-weight:600;")
        hdr.addWidget(ic); hdr.addWidget(ttl); hdr.addStretch(); lay.addLayout(hdr)
        self.val = QLabel("—")
        self.val.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;font-family:{FONTS['mono']};")
        lay.addWidget(self.val)

    def set_value(self, v: str, color: str = None):
        c = color or COLORS['text_primary']
        self.val.setText(v)
        self.val.setStyleSheet(
            f"color:{c};font-size:{FONTS['size_xl']};"
            f"font-weight:700;font-family:{FONTS['mono']};")


# ── Font scale toolbar ────────────────────────────────────────────────────────
class FontScaleBar(QWidget):
    """5-button font size selector that live-reloads the journal feed."""
    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        c = COLORS
        lay = QHBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        lbl = QLabel("Шрифт:")
        lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        lay.addWidget(lbl)

        self._btns: list[QPushButton] = []
        fs    = get_journal_font()
        sizes = ["XS","S","M","L","XL"]
        for i, name in enumerate(sizes):
            b = QPushButton(name)
            b.setFixedSize(28, 22)
            b.setCheckable(True)
            b.setChecked(i == fs.level())
            b.setProperty("scale_idx", i)
            b.setStyleSheet(self._style(i == fs.level()))
            b.clicked.connect(lambda checked, idx=i: self._pick(idx))
            lay.addWidget(b)
            self._btns.append(b)
        lay.addStretch()

    def _pick(self, idx: int):
        fs = get_journal_font()
        fs.set_level(idx)
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._style(i == idx))
        self._on_change()

    def _style(self, active: bool) -> str:
        c = COLORS
        if active:
            return (f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
                    f"border:1px solid {c['accent']};border-radius:4px;"
                    f"font-size:{FONTS['size_xs']};font-weight:700;}}")
        return (f"QPushButton{{background:{c['bg_elevated']};color:{c['text_muted']};"
                f"border:1px solid {c['border']};border-radius:4px;"
                f"font-size:{FONTS['size_xs']};}}"
                f"QPushButton:hover{{color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}")


# ── Entry row ─────────────────────────────────────────────────────────────────
class EntryRow(QWidget):
    def __init__(self, e: JournalEntry, parent=None):
        super().__init__(parent)
        self.entry = e
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build()

    def _build(self):
        c   = COLORS
        fs  = get_journal_font()
        fnt = f"font-size:{fs.px('sm')};font-family:{FONTS['mono']};"

        # Row height scales with font
        row_h = max(24, round(30 * fs.mult()))
        self.setFixedHeight(row_h)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10,0,10,0); lay.setSpacing(8)

        icon_ch, icon_col = EVENT_ICONS.get(self.entry.event, ("•", c['text_muted']))

        # Timestamp
        ts = datetime.fromtimestamp(self.entry.ts).strftime("%H:%M:%S")
        ts_l = QLabel(ts)
        ts_l.setFixedWidth(round(66 * fs.mult()))
        ts_l.setStyleSheet(f"color:{c['text_muted']};{fnt}background:transparent;")
        lay.addWidget(ts_l)

        # Icon
        ic = QLabel(icon_ch)
        ic.setFixedWidth(14)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(
            f"color:{icon_col};font-size:{fs.px('sm')};font-weight:700;background:transparent;")
        lay.addWidget(ic)

        # Macro name
        if self.entry.event != "step":
            nm = QLabel(self.entry.macro_name)
            nm.setFixedWidth(round(110 * fs.mult()))
            nm.setStyleSheet(
                f"color:{c['accent_bright']};font-size:{fs.px('sm')};"
                f"font-weight:600;background:transparent;")
            lay.addWidget(nm)

        # Detail
        dcol = {"started":c['success'],"stopped":c['accent_bright'],
                "step":c['text_secondary'],"error":c['danger']}.get(
                    self.entry.event, c['text_muted'])
        dl = QLabel(self.entry.detail)
        dl.setStyleSheet(f"color:{dcol};{fnt}background:transparent;")
        lay.addWidget(dl, 1)

        # Duration badge for stopped events
        if self.entry.event == "stopped" and self.entry.duration_ms:
            dur_txt = fmt_duration(self.entry.duration_ms)
            dur = QLabel(dur_txt)
            dur.setStyleSheet(
                f"color:{c['amber']};background:{c['amber_dim']};"
                f"border-radius:3px;padding:1px 6px;"
                f"font-size:{fs.px('xs')};font-family:{FONTS['mono']};")
            lay.addWidget(dur)

        bg = {"started":"#0D1F14","stopped":"#0A1220",
              "error":"#1F0D0D"}.get(self.entry.event,"transparent")
        self.setStyleSheet(f"background:{bg};border-bottom:1px solid {c['border']};")


# ── Main Log Page ─────────────────────────────────────────────────────────────
class LogPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_steps = True
        self._auto_scroll  = True
        self._rows: list[EntryRow] = []
        self._bar_data: dict[str, int] = {}
        self._build()
        self._connect_journal()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1500)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start()

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build(self):
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────────
        bar = QWidget(); bar.setFixedHeight(64)
        bar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(24,0,16,0); bl.setSpacing(10)
        tv = QVBoxLayout(); tv.setSpacing(1)
        t  = QLabel("Журнал")
        t.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;background:transparent;")
        s  = QLabel("История выполнения макросов — реальное время")
        s.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};background:transparent;")
        tv.addWidget(t); tv.addWidget(s); bl.addLayout(tv); bl.addStretch()
        self.live_dot = QLabel("● LIVE")
        self.live_dot.setStyleSheet(
            f"color:{c['success']};font-size:{FONTS['size_xs']};font-weight:700;"
            f"background:{c['success_dim']};border:1px solid {c['success']};"
            f"border-radius:4px;padding:2px 8px;")
        bl.addWidget(self.live_dot)
        self._btn(bl,"⧉  Открыть в окне",self._pop_out,c['bg_elevated'],c['text_secondary'])
        self._btn(bl,"🗑  Очистить",       self._clear,  c['danger_dim'], c['danger'])
        root.addWidget(bar)

        # ── Filter + font bar ─────────────────────────────────────────────────
        fb = QWidget(); fb.setFixedHeight(40)
        fb.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        fl = QHBoxLayout(fb); fl.setContentsMargins(14,0,14,0); fl.setSpacing(14)

        self.cb_steps = QCheckBox("Скрыть нажатия")
        self.cb_steps.setChecked(True)
        self.cb_steps.setStyleSheet(
            f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.cb_steps.stateChanged.connect(self._toggle_steps)
        fl.addWidget(self.cb_steps)

        self.cb_scroll = QCheckBox("Авто-прокрутка")
        self.cb_scroll.setChecked(True)
        self.cb_scroll.setStyleSheet(
            f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.cb_scroll.stateChanged.connect(
            lambda v: setattr(self,'_auto_scroll',bool(v)))
        fl.addWidget(self.cb_scroll)

        # vertical divider
        dv = QFrame(); dv.setFrameShape(QFrame.Shape.VLine)
        dv.setStyleSheet(f"color:{c['border']};max-width:1px;")
        fl.addWidget(dv)

        # Font scale bar
        self._font_bar = FontScaleBar(self._on_font_change)
        fl.addWidget(self._font_bar)

        fl.addStretch()
        self.cnt_lbl = QLabel("0 событий")
        self.cnt_lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        fl.addWidget(self.cnt_lbl)
        root.addWidget(fb)

        # ── Splitter ──────────────────────────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(5)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle:horizontal{{
                background:{c['border_bright']};
            }}
            QSplitter::handle:horizontal:hover{{
                background:{c['accent']};
            }}
        """)

        # ── Left: live feed ───────────────────────────────────────────────────
        feed_w = QWidget(); feed_w.setStyleSheet("background:transparent;")
        feed_l = QVBoxLayout(feed_w)
        feed_l.setContentsMargins(0,0,0,0); feed_l.setSpacing(0)

        self.feed_scroll = QScrollArea()
        self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.feed_scroll.setStyleSheet("background:transparent;border:none;")
        self.feed_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.feed_inner = QWidget()
        self.feed_inner.setStyleSheet("background:transparent;")
        self.feed_lay = QVBoxLayout(self.feed_inner)
        self.feed_lay.setContentsMargins(0,0,0,0); self.feed_lay.setSpacing(0)
        self.feed_lay.addStretch()
        self.feed_scroll.setWidget(self.feed_inner)
        feed_l.addWidget(self.feed_scroll)
        self.splitter.addWidget(feed_w)

        # ── Right: stats ──────────────────────────────────────────────────────
        stats_w = QWidget()
        stats_w.setMinimumWidth(240)   # can be dragged wider/narrower
        stats_w.setStyleSheet(
            f"background:{c['bg_panel']};")
        sl = QVBoxLayout(stats_w)
        sl.setContentsMargins(14,14,14,14); sl.setSpacing(10)

        self._section(sl, "СТАТИСТИКА СЕССИИ")

        g1 = QWidget(); r1 = QHBoxLayout(g1)
        r1.setContentsMargins(0,0,0,0); r1.setSpacing(6)
        self.sc_runs  = StatCard("▶","Запусков");  r1.addWidget(self.sc_runs)
        self.sc_steps = StatCard("·","Нажатий");   r1.addWidget(self.sc_steps)
        sl.addWidget(g1)

        g2 = QWidget(); r2 = QHBoxLayout(g2)
        r2.setContentsMargins(0,0,0,0); r2.setSpacing(6)
        self.sc_err  = StatCard("⚠","Ошибок");    r2.addWidget(self.sc_err)
        self.sc_time = StatCard("⏱","Время");      r2.addWidget(self.sc_time)
        sl.addWidget(g2)

        self._sep(sl)
        self._section(sl,"ЗАДЕРЖКИ НАЖАТИЙ (мс)")

        delay_row = QHBoxLayout(); delay_row.setSpacing(10)
        self.delay_avg = self._mini_stat("avg","—")
        self.delay_min = self._mini_stat("min","—")
        self.delay_max = self._mini_stat("max","—")
        for w in (self.delay_avg, self.delay_min, self.delay_max):
            delay_row.addWidget(w)
        sl.addLayout(delay_row)

        self.sparkline = Sparkline()
        self.sparkline.setStyleSheet(
            f"border:1px solid {c['border']};border-radius:4px;")
        sl.addWidget(self.sparkline)

        self._sep(sl)
        self._section(sl,"ГРАФИК НАЖАТИЙ (по макросам)")

        from ui.widgets.line_chart import LineChart
        self.line_chart = LineChart(y_label="нажатий")
        self.line_chart.setMinimumHeight(160)
        self.line_chart.setStyleSheet(
            f"border:1px solid {c['border']};border-radius:6px;")
        sl.addWidget(self.line_chart, 1)

        self._sep(sl)
        self._section(sl,"ЗАПУСКИ ПО МАКРОСАМ")

        self.bar_chart = BarChart()
        self.bar_chart.setMinimumHeight(80)
        self.bar_chart.setStyleSheet(
            f"background:{c['bg_deep']};border-radius:6px;")
        sl.addWidget(self.bar_chart)

        self.splitter.addWidget(stats_w)
        self.splitter.setSizes([700, 330])
        root.addWidget(self.splitter, 1)

        # Live dot blink
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(800)
        self._live_timer.timeout.connect(self._blink)
        self._live_timer.start(); self._live_on = True

        # Chart tick
        self._step_buckets:    dict[str, int] = {}
        self._monitor_buckets: dict[str, int] = {}
        self._chart_series:    dict[str, object] = {}
        self._chart_tick = QTimer(self)
        self._chart_tick.setInterval(2000)
        self._chart_tick.timeout.connect(self._flush_chart_tick)
        self._chart_tick.start()

    # ── Journal ───────────────────────────────────────────────────────────────
    def _connect_journal(self):
        j = get_journal()
        j.signals.entry_added.connect(self._on_entry)
        j.signals.session_reset.connect(self._on_reset)
        for e in j.entries():
            self._on_entry(e, scroll=False)

    def _on_entry(self, e: JournalEntry, scroll=True):
        if e.event == "stopped":
            self._bar_data[e.macro_name] = self._bar_data.get(e.macro_name, 0) + 1
            self.bar_chart.set_data(list(self._bar_data.items()))

        if e.event == "step":
            if e.step_delay > 0:
                self.sparkline.push(e.step_delay)
            self._step_buckets[e.macro_name] = \
                self._step_buckets.get(e.macro_name, 0) + 1

        if self._filter_steps and e.event == "step":
            self.cnt_lbl.setText(f"{len(get_journal().entries())} событий")
            return

        row = EntryRow(e)
        self._rows.append(row)
        self.feed_lay.insertWidget(self.feed_lay.count()-1, row)
        if len(self._rows) > 1500:
            old = self._rows.pop(0); old.deleteLater()
        self.cnt_lbl.setText(f"{len(get_journal().entries())} событий")
        if scroll and self._auto_scroll:
            QTimer.singleShot(30, lambda: self.feed_scroll.verticalScrollBar().setValue(
                self.feed_scroll.verticalScrollBar().maximum()))

    def _flush_chart_tick(self):
        # Combine macro steps + monitor triggers for the chart
        combined = dict(self._step_buckets)
        for zone, cnt in self._monitor_buckets.items():
            key = f"👁{zone}"
            combined[key] = combined.get(key, 0) + cnt

        if not combined:
            for s in self._chart_series.values():
                s.push(0)
        else:
            for name, cnt in combined.items():
                if name not in self._chart_series:
                    from ui.widgets.line_chart import PALETTE
                    col = PALETTE[len(self._chart_series) % len(PALETTE)]
                    self._chart_series[name] = self.line_chart.add_series(name, col)
                self._chart_series[name].push(cnt)
            for name, s in self._chart_series.items():
                if name not in combined:
                    s.push(0)
            self._step_buckets.clear()
            self._monitor_buckets.clear()
        self.line_chart.update()

    def _on_reset(self):
        while self.feed_lay.count() > 1:
            item = self.feed_lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows.clear(); self._bar_data.clear()
        self.bar_chart.set_data([]); self.sparkline.clear()
        self.line_chart.clear_all(); self._chart_series.clear()
        self._step_buckets.clear()

    def _refresh_stats(self):
        s = get_journal().stats()
        self.sc_runs.set_value(
            str(s['runs']), COLORS['success'] if s['runs'] else None)
        self.sc_steps.set_value(str(s['steps']))
        self.sc_err.set_value(
            str(s['errors']), COLORS['danger'] if s['errors'] else None)
        self.sc_time.set_value(fmt_duration(s['total_ms']))

        if s['avg_delay']:
            self._set_mini(self.delay_avg, f"{s['avg_delay']}мс")
            self._set_mini(self.delay_min, f"{s['min_delay']}мс")
            self._set_mini(self.delay_max, f"{s['max_delay']}мс")

    def _on_font_change(self):
        """Rebuild feed with new font scale."""
        sizes = self._get_splitter_sizes()
        self._rebuild_feed()
        # Restore splitter sizes after rebuild
        QTimer.singleShot(10, lambda: self.splitter.setSizes(sizes))

    def _get_splitter_sizes(self) -> list[int]:
        return self.splitter.sizes()

    def _rebuild_feed(self):
        """Delete all EntryRow widgets and recreate with current font scale."""
        while self.feed_lay.count() > 1:
            item = self.feed_lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows.clear()
        for e in get_journal().entries():
            if self._filter_steps and e.event == "step":
                continue
            row = EntryRow(e)
            self._rows.append(row)
            self.feed_lay.insertWidget(self.feed_lay.count()-1, row)

    def _toggle_steps(self, v):
        self._filter_steps = bool(v)
        self._rebuild_feed()

    def _blink(self):
        self._live_on = not self._live_on
        c = COLORS
        if self._live_on:
            self.live_dot.setStyleSheet(
                f"color:{c['success']};font-size:{FONTS['size_xs']};font-weight:700;"
                f"background:{c['success_dim']};border:1px solid {c['success']};"
                f"border-radius:4px;padding:2px 8px;")
        else:
            self.live_dot.setStyleSheet(
                f"color:{c['success_dim']};font-size:{FONTS['size_xs']};font-weight:700;"
                f"background:transparent;border:1px solid {c['success_dim']};"
                f"border-radius:4px;padding:2px 8px;")

    def _clear(self):
        get_journal().clear(); self._refresh_stats()

    def _pop_out(self):
        w = LogWindow(); w.show()
        if not hasattr(self,'_floats'): self._floats=[]
        self._floats.append(w)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _section(self, lay, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.5px;background:transparent;")
        lay.addWidget(l)

    def _sep(self, lay):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            f"background:{COLORS['border']};max-height:1px;border:none;")
        lay.addWidget(f)

    def _btn(self, lay, text, slot, bg, fg):
        c = COLORS; b = QPushButton(text); b.setFixedHeight(32)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg};"
            f"border-radius:6px;padding:0 12px;"
            f"font-size:{FONTS['size_xs']};font-weight:600;}}"
            f"QPushButton:hover{{background:{fg};color:white;}}")
        b.clicked.connect(slot); lay.addWidget(b)

    def _mini_stat(self, label: str, val: str) -> QWidget:
        c = COLORS; w = QWidget()
        w.setStyleSheet("background:transparent;")
        l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        v = QLabel(val); v.setObjectName("val")
        v.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};"
            f"font-weight:700;font-family:{FONTS['mono']};background:transparent;")
        l.addWidget(lbl); l.addWidget(v)
        return w

    @staticmethod
    def _set_mini(w: QWidget, text: str):
        lbl = w.findChild(QLabel, "val")
        if lbl: lbl.setText(text)


# ── Floating window ───────────────────────────────────────────────────────────
class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MacroX — Журнал (живой)")
        self.setWindowFlags(Qt.WindowType.Window)
        self.resize(1100, 680); self.setMinimumSize(720, 460)
        from ui.theme import get_app_stylesheet
        self.setStyleSheet(get_app_stylesheet())
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0)
        lay.addWidget(TabbedLogPage())
        log.info("LogWindow opened as floating")


# ── Monitor Journal Tab ────────────────────────────────────────────────────────
class MonitorEntryRow(QWidget):
    """Compact row for a monitor trigger event."""
    def __init__(self, e, parent=None):
        super().__init__(parent)
        from core.font_scale import get_journal_font
        fs = get_journal_font()
        c  = COLORS
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(max(24, round(28 * fs.mult())))
        lay = QHBoxLayout(self); lay.setContentsMargins(10,0,10,0); lay.setSpacing(8)

        ts = datetime.fromtimestamp(e.ts).strftime("%H:%M:%S")
        tl = QLabel(ts); tl.setFixedWidth(round(66*fs.mult()))
        tl.setStyleSheet(f"color:{c['text_muted']};font-size:{fs.px('xs')};"
                         f"font-family:{FONTS['mono']};background:transparent;")
        lay.addWidget(tl)

        ic = QLabel("👁"); ic.setFixedWidth(16)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet("background:transparent;font-size:11px;")
        lay.addWidget(ic)

        zone_l = QLabel(e.macro_name); zone_l.setFixedWidth(round(120*fs.mult()))
        zone_l.setStyleSheet(f"color:{c['amber']};font-size:{fs.px('sm')};"
                              f"font-weight:600;background:transparent;")
        lay.addWidget(zone_l)

        det = QLabel(e.detail)
        det.setStyleSheet(f"color:{c['text_secondary']};font-size:{fs.px('xs')};"
                           f"font-family:{FONTS['mono']};background:transparent;")
        lay.addWidget(det, 1)

        self.setStyleSheet(f"background:#0F1A0A;border-bottom:1px solid {c['border']};")


class MonitorLogTab(QWidget):
    """Journal tab for monitor trigger events."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._auto_scroll = True
        self._build()
        self._connect()

    def _build(self):
        c = COLORS
        self.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Filter bar
        fb = QWidget(); fb.setFixedHeight(34)
        fb.setStyleSheet(f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        fl = QHBoxLayout(fb); fl.setContentsMargins(14,0,14,0); fl.setSpacing(14)
        self.cb_scroll = QCheckBox("Авто-прокрутка")
        self.cb_scroll.setChecked(True)
        self.cb_scroll.setStyleSheet(f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.cb_scroll.stateChanged.connect(lambda v: setattr(self,'_auto_scroll',bool(v)))
        fl.addWidget(self.cb_scroll); fl.addStretch()
        self.cnt_lbl = QLabel("0 срабатываний")
        self.cnt_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        fl.addWidget(self.cnt_lbl)
        lay.addWidget(fb)

        # Feed
        self.feed_scroll = QScrollArea(); self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.feed_scroll.setStyleSheet("background:transparent;border:none;")
        self.feed_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feed_inner = QWidget(); self.feed_inner.setStyleSheet("background:transparent;")
        self.feed_lay = QVBoxLayout(self.feed_inner)
        self.feed_lay.setContentsMargins(0,0,0,0); self.feed_lay.setSpacing(0)
        self.feed_lay.addStretch()
        self.feed_scroll.setWidget(self.feed_inner)
        lay.addWidget(self.feed_scroll, 1)

    def _connect(self):
        j = get_journal()
        j.signals.entry_added.connect(self._on_entry)
        j.signals.session_reset.connect(self._on_reset)
        for e in j.entries():
            if e.event == "monitor": self._on_entry(e, scroll=False)

    def _on_entry(self, e, scroll=True):
        if e.event != "monitor": return
        row = MonitorEntryRow(e)
        self._rows.append(row)
        self.feed_lay.insertWidget(self.feed_lay.count()-1, row)
        if len(self._rows) > 1000:
            old = self._rows.pop(0); old.deleteLater()
        n = sum(1 for r in self._rows)
        self.cnt_lbl.setText(f"{n} срабатываний")
        if scroll and self._auto_scroll:
            QTimer.singleShot(30, lambda: self.feed_scroll.verticalScrollBar().setValue(
                self.feed_scroll.verticalScrollBar().maximum()))

    def _on_reset(self):
        while self.feed_lay.count() > 1:
            item = self.feed_lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows.clear(); self.cnt_lbl.setText("0 срабатываний")


# ── Tabbed Log Page (wraps MacroLog + MonitorLog + future Blueprint) ──────────
class TabbedLogPage(QWidget):
    """
    Journal page with shared header+stats and per-tab feed.

    Layout:
      ┌─ Top bar (title, LIVE, open-window, clear) ──────────────────────────┐
      │  Filter bar (checkboxes, font scale, event counter)                  │
      │  Stats panel (4 StatCards + delay mini-stats + sparkline + charts)   │
      ├─ Tab switcher [📋 Макросы] [👁 Мониторинг] [🔷 Blueprint] ──────────┤
      └─ Tab feed (scrollable, per-tab) ──────────────────────────────────────┘
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")

        self._auto_scroll = True
        self._filter_steps = True
        self._rows_macro: list[QWidget] = []
        self._rows_mon:   list[QWidget] = []
        self._bar_data:   dict[str, int] = {}
        self._step_buckets: dict[str, int] = {}
        self._chart_series: dict[str, object] = {}

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Top bar (shared) ──────────────────────────────────────────────────
        bar = QWidget(); bar.setFixedHeight(64)
        bar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(24,0,16,0); bl.setSpacing(10)
        tv = QVBoxLayout(); tv.setSpacing(1)
        t  = QLabel("Журнал")
        t.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;background:transparent;")
        self._sub = QLabel("История выполнения — реальное время")
        self._sub.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};background:transparent;")
        tv.addWidget(t); tv.addWidget(self._sub)
        bl.addLayout(tv); bl.addStretch()

        self.live_dot = QLabel("● LIVE")
        self.live_dot.setStyleSheet(
            f"color:{c['success']};font-size:{FONTS['size_xs']};font-weight:700;"
            f"background:{c['success_dim']};border:1px solid {c['success']};"
            f"border-radius:4px;padding:2px 8px;")
        bl.addWidget(self.live_dot)
        self._mkbtn(bl, "⧉  Открыть в окне", self._pop_out, c['bg_elevated'], c['text_secondary'])
        self._mkbtn(bl, "🗑  Очистить",        self._clear,   c['danger_dim'],  c['danger'])
        root.addWidget(bar)

        # ── Filter + font bar (shared) ────────────────────────────────────────
        fb = QWidget(); fb.setFixedHeight(40)
        fb.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        fl = QHBoxLayout(fb); fl.setContentsMargins(14,0,14,0); fl.setSpacing(14)
        self.cb_steps = QCheckBox("Скрыть нажатия")
        self.cb_steps.setChecked(True)
        self.cb_steps.setStyleSheet(f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.cb_steps.stateChanged.connect(self._toggle_steps)
        fl.addWidget(self.cb_steps)
        self.cb_scroll = QCheckBox("Авто-прокрутка")
        self.cb_scroll.setChecked(True)
        self.cb_scroll.setStyleSheet(f"color:{c['text_secondary']};font-size:{FONTS['size_xs']};")
        self.cb_scroll.stateChanged.connect(lambda v: setattr(self,'_auto_scroll',bool(v)))
        fl.addWidget(self.cb_scroll)
        dv = QFrame(); dv.setFrameShape(QFrame.Shape.VLine)
        dv.setStyleSheet(f"color:{c['border']};max-width:1px;"); fl.addWidget(dv)
        self._font_bar = FontScaleBar(self._on_font_change); fl.addWidget(self._font_bar)
        fl.addStretch()
        self.cnt_lbl = QLabel("0 событий")
        self.cnt_lbl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        fl.addWidget(self.cnt_lbl)
        root.addWidget(fb)

        # ── Stats splitter area ───────────────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(5)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle:horizontal{{background:{c['border_bright']};}}
            QSplitter::handle:horizontal:hover{{background:{c['accent']};}}
        """)

        # Left side = tab area (tabs + feed)
        left_w = QWidget(); left_w.setStyleSheet("background:transparent;")
        left_l = QVBoxLayout(left_w); left_l.setContentsMargins(0,0,0,0); left_l.setSpacing(0)

        # Tab switcher
        tab_bar_w = QWidget(); tab_bar_w.setFixedHeight(40)
        tab_bar_w.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        tbl = QHBoxLayout(tab_bar_w); tbl.setContentsMargins(14,0,14,0); tbl.setSpacing(4)
        self._tab_btns: list[QPushButton] = []
        for i, (icon, label) in enumerate([
            ("📋", "Макросы"),
            ("👁", "Мониторинг"),
            ("🔷", "Blueprint"),
        ]):
            b = QPushButton(f"{icon}  {label}"); b.setFixedHeight(30); b.setCheckable(True)
            b.setChecked(i == 0)
            b.setStyleSheet(self._tab_style(i == 0))
            b.clicked.connect(lambda _, idx=i: self._switch(idx))
            tbl.addWidget(b); self._tab_btns.append(b)
        tbl.addStretch()
        left_l.addWidget(tab_bar_w)

        # Feed stack — one scroll area per tab
        self._feeds: list[QScrollArea] = []
        for _ in range(3):
            sa = QScrollArea(); sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setStyleSheet("background:transparent;border:none;")
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QWidget(); inner.setStyleSheet("background:transparent;")
            lay_i = QVBoxLayout(inner)
            lay_i.setContentsMargins(0,0,0,0); lay_i.setSpacing(0)
            lay_i.addStretch()
            sa.setWidget(inner)
            self._feeds.append(sa)
            left_l.addWidget(sa, 1)

        # Blueprint placeholder feed
        bp_inner = self._feeds[2].widget()
        lbl = QLabel("🔷 Blueprint — журнал будет здесь")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xl']};background:transparent;")
        bp_inner.layout().insertWidget(0, lbl)

        # Hide all but first tab
        self._feeds[1].hide(); self._feeds[2].hide()
        self.splitter.addWidget(left_w)

        # ── Right side: stats panel (shared) ─────────────────────────────────
        stats_w = QWidget(); stats_w.setMinimumWidth(240)
        stats_w.setStyleSheet(f"background:{c['bg_panel']};")
        sl = QVBoxLayout(stats_w); sl.setContentsMargins(14,14,14,14); sl.setSpacing(10)

        self._section(sl, "СТАТИСТИКА СЕССИИ")
        g1 = QWidget(); r1 = QHBoxLayout(g1); r1.setContentsMargins(0,0,0,0); r1.setSpacing(6)
        self.sc_runs  = StatCard("▶","Запусков");   r1.addWidget(self.sc_runs)
        self.sc_steps = StatCard("·","Нажатий");    r1.addWidget(self.sc_steps)
        sl.addWidget(g1)
        g2 = QWidget(); r2 = QHBoxLayout(g2); r2.setContentsMargins(0,0,0,0); r2.setSpacing(6)
        self.sc_err   = StatCard("⚠","Ошибок");    r2.addWidget(self.sc_err)
        self.sc_time  = StatCard("⏱","Время");      r2.addWidget(self.sc_time)
        sl.addWidget(g2)

        # Monitor triggers + uptime
        g3 = QWidget(); r3 = QHBoxLayout(g3); r3.setContentsMargins(0,0,0,0); r3.setSpacing(6)
        self.sc_triggers = StatCard("👁","Триггеры"); r3.addWidget(self.sc_triggers)
        self.sc_uptime   = StatCard("⏰","Сессия");   r3.addWidget(self.sc_uptime)
        sl.addWidget(g3)

        self._sep(sl)
        self._section(sl,"ЗАДЕРЖКИ НАЖАТИЙ (мс)")
        delay_row = QHBoxLayout(); delay_row.setSpacing(10)
        self.delay_avg = self._mini_stat("avg","—")
        self.delay_min = self._mini_stat("min","—")
        self.delay_max = self._mini_stat("max","—")
        for w in (self.delay_avg, self.delay_min, self.delay_max):
            delay_row.addWidget(w)
        sl.addLayout(delay_row)

        self.sparkline = Sparkline()
        self.sparkline.setStyleSheet(f"border:1px solid {c['border']};border-radius:4px;")
        sl.addWidget(self.sparkline)

        self._sep(sl)
        self._section(sl,"ГРАФИК НАЖАТИЙ (по макросам)")
        from ui.widgets.line_chart import LineChart
        self.line_chart = LineChart(y_label="нажатий")
        self.line_chart.setMinimumHeight(160)
        self.line_chart.setStyleSheet(f"border:1px solid {c['border']};border-radius:6px;")
        sl.addWidget(self.line_chart, 1)

        self._sep(sl)
        self._section(sl,"ЗАПУСКИ ПО МАКРОСАМ")
        self.bar_chart = BarChart()
        self.bar_chart.setMinimumHeight(80)
        self.bar_chart.setStyleSheet(f"background:{c['bg_deep']};border-radius:6px;")
        sl.addWidget(self.bar_chart)
        self.splitter.addWidget(stats_w)
        self.splitter.setSizes([700, 330])
        root.addWidget(self.splitter, 1)

        # Timers
        self._live_on = True
        self._live_timer = QTimer(self); self._live_timer.setInterval(800)
        self._live_timer.timeout.connect(self._blink); self._live_timer.start()

        self._stats_timer = QTimer(self); self._stats_timer.setInterval(1500)
        self._stats_timer.timeout.connect(self._refresh_stats); self._stats_timer.start()

        self._chart_tick = QTimer(self); self._chart_tick.setInterval(2000)
        self._chart_tick.timeout.connect(self._flush_chart_tick); self._chart_tick.start()

        self._cur_tab = 0
        self._connect_journal()

    # ── Tab switching ─────────────────────────────────────────────────────────
    def _switch(self, idx: int):
        self._cur_tab = idx
        for i, (b, sa) in enumerate(zip(self._tab_btns, self._feeds)):
            active = i == idx
            b.setChecked(active)
            b.setStyleSheet(self._tab_style(active))
            sa.setVisible(active)
        subs = [
            "История выполнения макросов — реальное время",
            "Срабатывания зон мониторинга — реальное время",
            "Blueprint — история выполнения сценариев",
        ]
        self._sub.setText(subs[idx])

    def _tab_style(self, active: bool) -> str:
        c = COLORS
        if active:
            return (f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
                    f"border:1px solid {c['accent']};border-radius:6px;"
                    f"font-size:{FONTS['size_xs']};font-weight:700;padding:0 12px;}}")
        return (f"QPushButton{{background:transparent;color:{c['text_muted']};"
                f"border:1px solid transparent;border-radius:6px;"
                f"font-size:{FONTS['size_xs']};padding:0 12px;}}"
                f"QPushButton:hover{{color:{c['text_primary']};background:{c['bg_elevated']};}}")

    # ── Journal connection ────────────────────────────────────────────────────
    def _connect_journal(self):
        j = get_journal()
        j.signals.entry_added.connect(self._on_entry)
        j.signals.session_reset.connect(self._on_reset)
        for e in j.entries():
            self._on_entry(e, scroll=False)

    def _on_entry(self, e: JournalEntry, scroll=True):
        # Route to correct tab feed
        if e.event == "monitor":
            self._add_to_feed(1, MonitorEntryRow(e), self._rows_mon, scroll)
            # Track for line chart
            self._monitor_buckets[e.macro_name] =                 self._monitor_buckets.get(e.macro_name, 0) + 1
            self._update_cnt()
            return

        # Stats for macro events
        if e.event == "stopped":
            self._bar_data[e.macro_name] = self._bar_data.get(e.macro_name, 0) + 1
            self.bar_chart.set_data(list(self._bar_data.items()))
        if e.event == "step" and e.step_delay > 0:
            self.sparkline.push(e.step_delay)
            self._step_buckets[e.macro_name] = self._step_buckets.get(e.macro_name, 0) + 1

        if self._filter_steps and e.event == "step":
            self._update_cnt(); return

        row = EntryRow(e)
        self._add_to_feed(0, row, self._rows_macro, scroll)
        self._update_cnt()

    def _add_to_feed(self, tab_idx: int, row: QWidget, rows_list: list, scroll: bool):
        feed_inner = self._feeds[tab_idx].widget()
        lay = feed_inner.layout()
        rows_list.append(row)
        lay.insertWidget(lay.count()-1, row)
        if len(rows_list) > 1500:
            old = rows_list.pop(0); old.deleteLater()
        if scroll and self._auto_scroll and self._cur_tab == tab_idx:
            QTimer.singleShot(30, lambda: self._feeds[tab_idx].verticalScrollBar().setValue(
                self._feeds[tab_idx].verticalScrollBar().maximum()))

    def _update_cnt(self):
        n = len(get_journal().entries())
        self.cnt_lbl.setText(f"{n} событий")

    def _flush_chart_tick(self):
        if not self._step_buckets:
            for s in self._chart_series.values(): s.push(0)
        else:
            for name, cnt in self._step_buckets.items():
                if name not in self._chart_series:
                    from ui.widgets.line_chart import PALETTE
                    col = PALETTE[len(self._chart_series) % len(PALETTE)]
                    self._chart_series[name] = self.line_chart.add_series(name, col)
                self._chart_series[name].push(cnt)
            for name, s in self._chart_series.items():
                if name not in self._step_buckets: s.push(0)
            self._step_buckets.clear()
        self.line_chart.update()

    def _on_reset(self):
        for rows, feed_idx in [(self._rows_macro, 0), (self._rows_mon, 1)]:
            feed_inner = self._feeds[feed_idx].widget()
            lay = feed_inner.layout()
            while lay.count() > 1:
                item = lay.takeAt(0)
                if item and item.widget(): item.widget().deleteLater()
            rows.clear()
        self._bar_data.clear(); self.bar_chart.set_data([])
        self.sparkline.clear(); self.line_chart.clear_all()
        self._chart_series.clear()
        self._step_buckets.clear()
        self._monitor_buckets.clear()

    def _refresh_stats(self):
        s = get_journal().stats()

        # Macro runs & steps
        self.sc_runs.set_value(str(s['runs']),   COLORS['success'] if s['runs']     else None)
        self.sc_steps.set_value(str(s['steps']), COLORS['accent']  if s['steps']    else None)
        self.sc_err.set_value(str(s['errors']),  COLORS['danger']  if s['errors']   else None)

        # Total macro execution time (sum of all runs)
        if s['total_ms']:
            self.sc_time.set_value(fmt_duration(s['total_ms']))
        else:
            self.sc_time.set_value("—")

        # Monitor triggers
        self.sc_triggers.set_value(
            str(s.get('monitors', 0)), COLORS['amber'] if s.get('monitors', 0) else None)

        # Uptime — only while something was active this session
        self.sc_uptime.set_value(fmt_duration(s.get('uptime_ms', 0)))

        # Bar chart: macro runs + zone triggers combined
        bar_data = list(s.get('macro_runs', {}).items())
        for zone, cnt in s.get('zone_triggers', {}).items():
            bar_data.append((f"👁 {zone}", cnt))
        if bar_data:
            self.bar_chart.set_data(bar_data)

        # Delay stats from macro steps
        if s['avg_delay']:
            self._set_mini(self.delay_avg, f"{s['avg_delay']}мс")
            self._set_mini(self.delay_min, f"{s['min_delay']}мс")
            self._set_mini(self.delay_max, f"{s['max_delay']}мс")

    def _toggle_steps(self, v):
        self._filter_steps = bool(v)
        self._rebuild_macro_feed()

    def _on_font_change(self):
        sizes = self.splitter.sizes()
        self._rebuild_macro_feed()
        QTimer.singleShot(10, lambda: self.splitter.setSizes(sizes))

    def _rebuild_macro_feed(self):
        feed_inner = self._feeds[0].widget()
        lay = feed_inner.layout()
        while lay.count() > 1:
            item = lay.takeAt(0)
            if item and item.widget(): item.widget().deleteLater()
        self._rows_macro.clear()
        for e in get_journal().entries():
            if e.event == "monitor": continue
            if self._filter_steps and e.event == "step": continue
            row = EntryRow(e)
            self._rows_macro.append(row)
            lay.insertWidget(lay.count()-1, row)

    def _blink(self):
        self._live_on = not self._live_on
        c = COLORS
        if self._live_on:
            self.live_dot.setStyleSheet(
                f"color:{c['success']};font-size:{FONTS['size_xs']};font-weight:700;"
                f"background:{c['success_dim']};border:1px solid {c['success']};"
                f"border-radius:4px;padding:2px 8px;")
        else:
            self.live_dot.setStyleSheet(
                f"color:{c['success_dim']};font-size:{FONTS['size_xs']};font-weight:700;"
                f"background:transparent;border:1px solid {c['success_dim']};"
                f"border-radius:4px;padding:2px 8px;")

    def _clear(self):
        get_journal().clear(); self._refresh_stats()

    def _pop_out(self):
        w = LogWindow(); w.show()
        if not hasattr(self,'_floats'): self._floats = []
        self._floats.append(w)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _section(self, lay, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.5px;background:transparent;")
        lay.addWidget(l)

    def _sep(self, lay):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background:{COLORS['border']};max-height:1px;border:none;")
        lay.addWidget(f)

    def _mkbtn(self, lay, text, slot, bg, fg):
        b = QPushButton(text); b.setFixedHeight(32)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg};"
            f"border-radius:6px;padding:0 12px;font-size:{FONTS['size_xs']};font-weight:600;}}"
            f"QPushButton:hover{{background:{fg};color:white;}}")
        b.clicked.connect(slot); lay.addWidget(b)

    def _mini_stat(self, label: str, val: str) -> QWidget:
        c = COLORS; w = QWidget(); w.setStyleSheet("background:transparent;")
        l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        v = QLabel(val); v.setObjectName("val")
        v.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};"
            f"font-weight:700;font-family:{FONTS['mono']};background:transparent;")
        l.addWidget(lbl); l.addWidget(v)
        return w

    @staticmethod
    def _set_mini(w: QWidget, text: str):
        lbl = w.findChild(QLabel, "val")
        if lbl: lbl.setText(text)
