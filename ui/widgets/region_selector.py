"""
MacroX — Screen region selector overlay v2.
Supports two selection modes:
  RECT   — classic drag rectangle
  CIRCLE — click center, drag to edge; emits bounding square of the circle

Signals:
  region_selected(x, y, w, h)          — for both modes
  circle_selected(cx, cy, r)           — circle-specific
  cancelled()
"""
import math, logging
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QRect, QPoint, QPointF, pyqtSignal
from PyQt6.QtGui     import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient

log = logging.getLogger(__name__)


class RegionSelectorOverlay(QWidget):
    region_selected = pyqtSignal(int, int, int, int)   # x, y, w, h (bounding box)
    circle_selected = pyqtSignal(int, int, int)        # cx, cy, r
    cancelled       = pyqtSignal()

    def __init__(self, mode: str = "rect", parent=None):
        """
        mode: "rect"   — drag rectangle
              "circle" — click center then drag to set radius
        """
        super().__init__(parent)
        self._mode   = mode
        self._start: QPoint | None = None
        self._end:   QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)

        total = self.rect()
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QRect
        total = QRect()
        for screen in QApplication.screens():
            total = total.united(screen.geometry())
        self.setGeometry(total)
        self.showFullScreen()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit(); self.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.pos(); self._end = e.pos(); self.update()

    def mouseMoveEvent(self, e):
        if self._start:
            self._end = e.pos(); self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._start:
            self._end = e.pos()
            if self._mode == "rect":
                rect = QRect(self._start, self._end).normalized()
                if rect.width() > 4 and rect.height() > 4:
                    self.region_selected.emit(
                        rect.x(), rect.y(), rect.width(), rect.height())
                else:
                    self.cancelled.emit()
            else:  # circle
                cx, cy, r = self._get_circle()
                if r > 4:
                    self.circle_selected.emit(cx, cy, r)
                    self.region_selected.emit(cx-r, cy-r, r*2, r*2)
                else:
                    self.cancelled.emit()
            self.close()

    # ── Drawing ───────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        if not (self._start and self._end):
            # Instructions
            p.setPen(QColor(255, 255, 255, 200))
            f = QFont("Segoe UI", 14); p.setFont(f)
            if self._mode == "rect":
                hint = "Нарисуйте прямоугольник\nEsc — отмена"
            else:
                hint = "Кликните в центр, потяните к краю круга\nEsc — отмена"
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, hint)
            return

        if self._mode == "rect":
            self._draw_rect(p)
        else:
            self._draw_circle(p)

    def _draw_rect(self, p: QPainter):
        rect = QRect(self._start, self._end).normalized()
        # Clear
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(rect, QColor(0,0,0,0))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Border
        p.setPen(QPen(QColor("#3D8EF0"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        # Corner handles
        sz = 8; p.setBrush(QColor("#5AA3FF")); p.setPen(Qt.PenStyle.NoPen)
        for cx, cy in [(rect.left(),rect.top()),(rect.right(),rect.top()),
                       (rect.left(),rect.bottom()),(rect.right(),rect.bottom())]:
            p.drawRect(cx-sz//2, cy-sz//2, sz, sz)
        self._draw_label(p, rect.x(), rect.y(),
                         f"{rect.width()} × {rect.height()}  ({rect.x()}, {rect.y()})")

    def _draw_circle(self, p: QPainter):
        cx, cy, r = self._get_circle()
        # Clear circle area
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setBrush(QColor(0,0,0,0)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(cx, cy), r, r)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Circle border
        p.setPen(QPen(QColor("#F05A3D"), 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPoint(cx, cy), r, r)
        # Center crosshair
        p.setPen(QPen(QColor("#F09D3D"), 1))
        p.drawLine(cx-10, cy, cx+10, cy)
        p.drawLine(cx, cy-10, cx, cy+10)
        # Radius line
        p.setPen(QPen(QColor("#F09D3D"), 1, Qt.PenStyle.DashLine))
        p.drawLine(cx, cy, self._end.x(), self._end.y())
        # Handles on circle edge at 4 cardinal points
        p.setBrush(QColor("#F05A3D")); p.setPen(Qt.PenStyle.NoPen)
        sz = 6
        for hx, hy in [(cx+r,cy),(cx-r,cy),(cx,cy+r),(cx,cy-r)]:
            p.drawRect(hx-sz//2, hy-sz//2, sz, sz)
        self._draw_label(p, cx-r, cy-r,
                         f"⌀{r*2}px  r={r}  ({cx}, {cy})", color="#F09D3D")

    def _get_circle(self) -> tuple[int,int,int]:
        if not (self._start and self._end):
            return 0, 0, 0
        cx = self._start.x(); cy = self._start.y()
        dx = self._end.x() - cx; dy = self._end.y() - cy
        r  = int(math.sqrt(dx*dx + dy*dy))
        return cx, cy, r

    def _draw_label(self, p: QPainter, lx: int, ly: int, text: str,
                    color: str = "#5AA3FF"):
        f = QFont("Segoe UI", 11); f.setBold(True); p.setFont(f)
        ly2 = ly - 22 if ly > 30 else ly + 10
        fm  = p.fontMetrics()
        tw  = fm.horizontalAdvance(text) + 12
        p.fillRect(lx, ly2-16, tw, 22, QColor(0x1A,0x1E,0x2A,220))
        p.setPen(QColor(color)); p.drawText(lx+6, ly2, text)
