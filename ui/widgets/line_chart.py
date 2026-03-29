"""
MacroX — Multi-line chart widget.
"""
import math
from collections import deque
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush,
                          QPainterPath, QFont, QFontMetrics)
from ui.theme import COLORS, FONTS

PALETTE = ["#5AA3FF","#F0A030","#2ECC71","#E74C3C",
           "#9B59B6","#1ABC9C","#E67E22","#EC407A"]


class Series:
    def __init__(self, name: str, color: str, maxlen: int = 300):
        self.name   = name
        self.color  = color
        self.values: deque = deque(maxlen=maxlen)
    def push(self, v: float): self.values.append(v)
    def data(self) -> list:   return list(self.values)


class LineChart(QWidget):
    def __init__(self, y_label: str = "", parent=None):
        super().__init__(parent)
        self._y_label  = y_label
        self._series:  list[Series] = []
        self._PL, self._PR, self._PT, self._PB = 54, 16, 8, 36
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(160)

    def add_series(self, name: str, color: str = None, maxlen: int = 300) -> Series:
        color = color or PALETTE[len(self._series) % len(PALETTE)]
        s = Series(name, color, maxlen)
        self._series.append(s)
        return s

    def get_series(self, name: str):
        for s in self._series:
            if s.name == name: return s
        return None

    def clear_all(self):
        for s in self._series: s.values.clear()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        c = COLORS

        p.fillRect(0, 0, W, H, QColor(c['bg_deep']))

        # Legend
        leg_h = self._draw_legend(p, W)
        PT    = self._PT + leg_h + (4 if leg_h else 0)
        PL, PR, PB = self._PL, self._PR, self._PB

        pw = W - PL - PR
        ph = H - PT - PB
        if pw < 20 or ph < 20: return

        all_vals = [v for s in self._series for v in s.values]
        if not all_vals:
            self._empty(p, W, H); return

        y_max = max(all_vals) * 1.15 or 10
        y_min = 0
        y_rng = y_max - y_min or 1

        self._grid(p, PL, PT, pw, ph, y_min, y_max)
        self._axes(p, PL, PT, pw, ph, y_min, y_max)

        p.setClipRect(PL, PT, pw, ph)
        for s in self._series:
            d = s.data()
            if len(d) >= 2:
                self._curve(p, d, s.color, PL, PT, pw, ph, y_min, y_rng)
        p.setClipping(False)

        if self._y_label:
            p.save()
            p.translate(11, H // 2)
            p.rotate(-90)
            p.setPen(QColor(c['text_muted']))
            f = QFont(FONTS['ui']); f.setPixelSize(9); p.setFont(f)
            p.drawText(QRect(-40, -8, 80, 16), Qt.AlignmentFlag.AlignCenter, self._y_label)
            p.restore()

    def _draw_legend(self, p, W) -> int:
        items = [(s.name, s.color) for s in self._series if s.values]
        if not items: return 0
        f = QFont(FONTS['ui']); f.setPixelSize(10); p.setFont(f)
        fm = QFontMetrics(f)
        x, y, row_h = self._PL, self._PT + 2, 12
        for name, color in items:
            tw = fm.horizontalAdvance(name)
            iw = tw + 20
            if x + iw > W - self._PR:
                x = self._PL; y += row_h + 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(x, y + 2, 7, 7)
            p.setPen(QColor(COLORS['text_secondary']))
            p.drawText(x + 10, y, tw + 4, row_h, Qt.AlignmentFlag.AlignVCenter, name)
            x += iw + 6
        return y + row_h - self._PT

    def _grid(self, p, px, py, pw, ph, y_min, y_max):
        pen = QPen(QColor(COLORS['border']), 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        for t in self._ticks(y_min, y_max):
            frac = (t - y_min) / (y_max - y_min)
            y    = int(py + ph - frac * ph)
            p.drawLine(px, y, px + pw, y)

    def _axes(self, p, px, py, pw, ph, y_min, y_max):
        c = COLORS
        p.setPen(QPen(QColor(c['border_bright']), 1))
        p.drawLine(px, py, px, py + ph)
        p.drawLine(px, py + ph, px + pw, py + ph)

        f = QFont(FONTS['mono']); f.setPixelSize(9); p.setFont(f)
        p.setPen(QColor(c['text_muted']))
        for t in self._ticks(y_min, y_max):
            frac = (t - y_min) / (y_max - y_min)
            y    = int(py + ph - frac * ph)
            lbl  = str(int(t)) if t == int(t) else f"{t:.0f}"
            p.drawText(0, y - 8, px - 4, 16,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, lbl)

    def _curve(self, p, data, color, px, py, pw, ph, y_min, y_rng):
        n = len(data)
        col = QColor(color)

        def pt(i):
            x = px + i / (n - 1) * pw
            y = py + ph - (data[i] - y_min) / y_rng * ph
            return x, y

        # Fill
        path = QPainterPath()
        x0, y0 = pt(0)
        path.moveTo(x0, py + ph)
        path.lineTo(x0, y0)
        for i in range(1, n):
            x1, y1 = pt(i)
            cx = (x0 + x1) / 2
            path.cubicTo(cx, y0, cx, y1, x1, y1)
            x0, y0 = x1, y1
        path.lineTo(x0, py + ph)
        path.closeSubpath()
        fc = QColor(col); fc.setAlpha(30)
        p.fillPath(path, QBrush(fc))

        # Line
        pen = QPen(col, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        x0, y0 = pt(0)
        for i in range(1, n):
            x1, y1 = pt(i)
            cx = (x0 + x1) / 2
            lp = QPainterPath()
            lp.moveTo(x0, y0)
            lp.cubicTo(cx, y0, cx, y1, x1, y1)
            p.drawPath(lp)
            x0, y0 = x1, y1

        # Last value dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(int(x0)-4, int(y0)-4, 8, 8)
        dot_bg = QColor(COLORS['bg_deep'])
        p.setBrush(dot_bg)
        p.drawEllipse(int(x0)-2, int(y0)-2, 4, 4)

    def _empty(self, p, W, H):
        p.setPen(QColor(COLORS['text_muted']))
        f = QFont(FONTS['ui']); f.setPixelSize(12); p.setFont(f)
        p.drawText(0, 0, W, H, Qt.AlignmentFlag.AlignCenter,
                   "Нет данных — запустите макрос")

    @staticmethod
    def _ticks(lo, hi, count=5):
        rng  = hi - lo or 1
        step = rng / count
        mag  = 10 ** math.floor(math.log10(max(step, 1e-9)))
        step = math.ceil(step / mag) * mag or 1
        t    = math.ceil(lo / step) * step
        res  = []
        while t <= hi + 1e-9:
            res.append(t); t += step
            if len(res) > 10: break
        return res
