"""
MacroX — Screen region selector overlay.
Full-screen transparent window; user drags a rectangle to select a zone.
"""
import logging
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui     import QPainter, QColor, QPen, QFont, QScreen

log = logging.getLogger(__name__)


class RegionSelectorOverlay(QWidget):
    """
    Semi-transparent fullscreen overlay.
    User clicks+drags to select a screen region.
    Emits region_selected(x, y, w, h) on mouse release.
    Press Escape to cancel.
    """
    region_selected = pyqtSignal(int, int, int, int)  # x, y, w, h
    cancelled       = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start: QPoint | None = None
        self._end:   QPoint | None = None
        self._done   = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Cover all screens
        total = QRect()
        for screen in QApplication.screens():
            total = total.united(screen.geometry())
        self.setGeometry(total)
        self.showFullScreen()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = e.pos()
            self._end   = e.pos()
            self.update()

    def mouseMoveEvent(self, e):
        if self._start:
            self._end = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._start:
            self._end = e.pos()
            rect = self._get_rect()
            if rect.width() > 4 and rect.height() > 4:
                self.region_selected.emit(
                    rect.x(), rect.y(), rect.width(), rect.height()
                )
            else:
                self.cancelled.emit()
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)

        # Dim the whole screen
        p.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self._start and self._end:
            rect = self._get_rect()

            # Clear selection area
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(rect, QColor(0,0,0,0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Border
            pen = QPen(QColor("#3D8EF0"), 2)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)

            # Corner handles
            sz = 8
            p.setBrush(QColor("#5AA3FF")); p.setPen(Qt.PenStyle.NoPen)
            for cx, cy in [
                (rect.left(),  rect.top()),
                (rect.right(), rect.top()),
                (rect.left(),  rect.bottom()),
                (rect.right(), rect.bottom()),
            ]:
                p.drawRect(cx - sz//2, cy - sz//2, sz, sz)

            # Dimension label
            lbl = f"{rect.width()} × {rect.height()}  ({rect.x()}, {rect.y()})"
            f = QFont("Segoe UI", 11); f.setBold(True); p.setFont(f)
            lx = rect.x()
            ly = rect.y() - 22 if rect.y() > 30 else rect.bottom() + 6

            # Label background
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(lbl) + 12
            p.fillRect(lx, ly - 16, tw, 22, QColor(0x1A, 0x1E, 0x2A, 220))
            p.setPen(QColor("#5AA3FF"))
            p.drawText(lx + 6, ly, lbl)

        else:
            # Instructions
            p.setPen(QColor(255, 255, 255, 180))
            f = QFont("Segoe UI", 14); p.setFont(f)
            p.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Выделите область мышью\n\nEsc — отмена"
            )

    def _get_rect(self) -> QRect:
        return QRect(self._start, self._end).normalized()
