"""
MacroX — Splash Screen

Shown while the app initializes. Closes automatically when
the main window calls splash.finish(main_window).

Design: dark card, animated spinner, step-by-step progress log.
"""
import math
from PyQt6.QtWidgets import QSplashScreen, QApplication, QWidget, QLabel
from PyQt6.QtCore    import Qt, QTimer, QRect, QPoint, pyqtSignal, QObject
from PyQt6.QtGui     import (QPainter, QColor, QFont, QPen, QBrush,
                              QLinearGradient, QPixmap, QFontMetrics)


# ── Signals (so background threads can push step updates) ─────────────────────
class _SplashSignals(QObject):
    step   = pyqtSignal(str)   # short step label
    done   = pyqtSignal()      # loading complete

splash_signals = _SplashSignals()


# ── Custom splash widget ───────────────────────────────────────────────────────
class MacroXSplash(QWidget):
    """
    Frameless translucent splash window.
    - Spinning arc indicator
    - App name + version
    - Rolling step log (last 4 steps visible)
    """
    WIDTH  = 480
    HEIGHT = 300

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._center_on_screen()

        self._angle   = 0
        self._steps   = []
        self._done    = False
        self._alpha   = 255          # for fade-out

        # Spinner timer
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(16)        # ~60 fps
        self._spin_timer.timeout.connect(self._tick)
        self._spin_timer.start()

        # Fade-out timer (used when done)
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)
        self._fade_timer.timeout.connect(self._fade)

        # Connect signals
        splash_signals.step.connect(self.add_step)
        splash_signals.done.connect(self._on_done)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.geometry()
            self.move(
                sg.x() + (sg.width()  - self.WIDTH)  // 2,
                sg.y() + (sg.height() - self.HEIGHT) // 2,
            )

    def add_step(self, text: str):
        self._steps.append(text)
        if len(self._steps) > 6:
            self._steps.pop(0)
        self.update()

    def _on_done(self):
        self._done = True
        self._spin_timer.stop()
        self.add_step("✓  Готово")
        QTimer.singleShot(400, self._start_fade)

    def _start_fade(self):
        self._fade_timer.start()

    def _fade(self):
        self._alpha = max(0, self._alpha - 18)
        self.setWindowOpacity(self._alpha / 255)
        if self._alpha <= 0:
            self._fade_timer.stop()
            self.close()

    def _tick(self):
        self._angle = (self._angle + 4) % 360
        self.update()

    # ── Paint ──────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.WIDTH, self.HEIGHT

        # ── Background card ──────────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        # Shadow (offset rect, semi-transparent)
        shadow_col = QColor(0, 0, 0, 60)
        for i in range(8, 0, -1):
            p.setBrush(shadow_col)
            p.drawRoundedRect(i, i+2, W-i*2, H-i*2, 16, 16)

        # Card fill
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, QColor(0x16, 0x1B, 0x2E))
        grad.setColorAt(1.0, QColor(0x0D, 0x11, 0x1E))
        p.setBrush(grad)
        p.drawRoundedRect(0, 0, W, H, 16, 16)

        # Card border
        p.setPen(QPen(QColor(0x2A, 0x35, 0x55), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, W-2, H-2, 15, 15)

        # ── Spinner ───────────────────────────────────────────────────────────
        CX, CY, R = 64, H // 2, 28
        if not self._done:
            # Track arc
            p.setPen(QPen(QColor(0x2A, 0x35, 0x55), 4,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(CX-R, CY-R, R*2, R*2, 0, 360*16)
            # Spinning arc
            arc_pen = QPen(QColor(0x3D, 0x8E, 0xF0), 4,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            start = (90 - self._angle) * 16
            p.drawArc(CX-R, CY-R, R*2, R*2, start, -270*16)
        else:
            # Done checkmark circle
            p.setPen(QPen(QColor(0x2E, 0xCC, 0x71), 3,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(CX-R, CY-R, R*2, R*2, 0, 360*16)
            p.setPen(QPen(QColor(0x2E, 0xCC, 0x71), 3,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(CX-10, CY+2, CX-4, CY+8)
            p.drawLine(CX-4,  CY+8, CX+11, CY-8)

        # ── Title ─────────────────────────────────────────────────────────────
        TX = CX + R + 20
        f_title = QFont("Segoe UI", 22, QFont.Weight.Bold)
        p.setFont(f_title)
        p.setPen(QColor(0xF0, 0xF4, 0xFF))
        p.drawText(TX, 70, "MacroX")

        f_sub = QFont("Segoe UI", 10)
        p.setFont(f_sub)
        p.setPen(QColor(0x5A, 0x6A, 0x9A))
        p.drawText(TX, 93, "Automation Platform  v0.1.0")

        # Thin separator line
        p.setPen(QPen(QColor(0x2A, 0x35, 0x55), 1))
        p.drawLine(TX, 104, W - 24, 104)

        # ── Step log ──────────────────────────────────────────────────────────
        f_step = QFont("Segoe UI", 9)
        p.setFont(f_step)
        fm     = QFontMetrics(f_step)
        LH     = 18           # line height
        log_y  = 118
        visible = self._steps[-5:] if self._steps else ["Инициализация…"]

        for i, step in enumerate(visible):
            progress = i / max(len(visible) - 1, 1)
            alpha    = int(80 + 175 * progress)   # older lines fade out
            if i == len(visible) - 1:
                p.setPen(QColor(0xA0, 0xC4, 0xFF, 230))    # current = bright
            else:
                p.setPen(QColor(0x4A, 0x5A, 0x80, alpha))  # older = muted
            # Truncate if too long
            text = fm.elidedText(step, Qt.TextElideMode.ElideRight, W - TX - 20)
            p.drawText(TX, log_y + i * LH, text)

        # ── Bottom hint ───────────────────────────────────────────────────────
        f_hint = QFont("Segoe UI", 8)
        p.setFont(f_hint)
        p.setPen(QColor(0x2A, 0x35, 0x55))
        p.drawText(TX, H - 16, "Не закрывайте это окно…")
