"""
MacroX — Main Window
"""
import logging
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout,
    QStackedWidget, QLabel, QPushButton)
from PyQt6.QtCore import QSize, QTimer
from ui.theme import get_app_stylesheet, COLORS, FONTS
from ui.sidebar import Sidebar
from ui.pages.macros_page import MacrosPage
from ui.pages.placeholder_pages import SettingsPage, MonitorPage, BlueprintPage, LogPage, StatePage
from core.logger import trace_calls

log = logging.getLogger(__name__)


class StatusIndicator(QWidget):
    """
    Triple status bar: [● Макрос] [● Мониторинг] [● Blueprint]
    Each indicator is independent — no coupling between states.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        c = COLORS
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 8, 0); lay.setSpacing(0)

        def _sep():
            s = QLabel("|")
            s.setStyleSheet(f"color:{c['border']};background:transparent;padding:0 4px;")
            return s

        # Macro indicator
        self.macro_led  = self._make_led("▶", "Макросы")
        # Monitor indicator
        self.mon_led    = self._make_led("👁", "Мониторинг")
        # Blueprint indicator
        self.bp_led     = self._make_led("🔷", "Blueprint")

        lay.addWidget(self.macro_led)
        lay.addWidget(_sep())
        lay.addWidget(self.mon_led)
        lay.addWidget(_sep())
        lay.addWidget(self.bp_led)

    def _make_led(self, icon: str, label: str) -> QWidget:
        c = COLORS
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(6, 0, 6, 0); lay.setSpacing(4)
        dot = QLabel("●"); dot.setFixedWidth(11)
        dot.setObjectName("dot")
        dot.setStyleSheet(f"color:{c['text_muted']};font-size:10px;background:transparent;border:none;")
        text = QLabel(f"{icon} {label}")
        text.setObjectName("text")
        text.setStyleSheet(
            f"color:{c['text_muted']};background:transparent;"
            f"font-size:{FONTS['size_xs']};font-family:{FONTS['ui']};")
        lay.addWidget(dot); lay.addWidget(text)

        # Timer for pulse
        t = QTimer(w); t.setInterval(550)
        w._pulse_on   = True
        w._state      = "idle"
        w._active_col = c['success']
        def _blink():
            w._pulse_on = not w._pulse_on
            col = w._active_col if w._pulse_on else c['border']
            dot.setStyleSheet(f"color:{col};font-size:10px;background:transparent;border:none;")
        t.timeout.connect(_blink)
        w._timer = t
        w._dot   = dot
        w._text  = text
        return w

    def _set_led_idle(self, led: QWidget, label: str):
        c = COLORS
        led._timer.stop(); led._state = "idle"; led._pulse_on = True
        led._dot.setStyleSheet(
            f"color:{c['text_muted']};font-size:10px;background:transparent;border:none;")
        led._text.setStyleSheet(
            f"color:{c['text_muted']};background:transparent;"
            f"font-size:{FONTS['size_xs']};font-family:{FONTS['ui']};")

    def _set_led_active(self, led: QWidget, col: str, text: str):
        led._state = "active"; led._active_col = col
        led._dot.setStyleSheet(f"color:{col};font-size:10px;background:transparent;border:none;")
        led._text.setText(text)
        led._text.setStyleSheet(
            f"color:{col};background:transparent;"
            f"font-size:{FONTS['size_xs']};font-family:{FONTS['ui']};")
        if not led._timer.isActive(): led._timer.start()

    # ── Macro LED API ─────────────────────────────────────────────────────────
    def set_running(self, name: str):
        self._set_led_active(
            self.macro_led, COLORS['success'], f"▶ Активен: {name}")

    def set_idle(self):
        self._set_led_idle(self.macro_led, "▶ Макросы")
        self.macro_led._text.setText(f"▶ Макросы")

    def set_active_count(self, count: int):
        if count == 0:
            self.set_idle()
        else:
            lbl = f"▶ Активно: {count}" if count > 1 else f"▶ {self.macro_led._text.text().replace('▶ ','')}"
            self._set_led_active(self.macro_led, COLORS['success'], lbl)

    def set_error(self, msg: str = "Ошибка"):
        self._set_led_active(self.macro_led, COLORS['danger'], f"▶ {msg}")
        QTimer.singleShot(4000, lambda: self._set_led_idle(self.macro_led, "▶ Макросы"))

    # ── Monitor LED API ───────────────────────────────────────────────────────
    def set_monitor(self, running: bool):
        if running:
            self._set_led_active(self.mon_led, COLORS['amber'], "👁 Мониторинг активен")
        else:
            self._set_led_idle(self.mon_led, "👁 Мониторинг")
            self.mon_led._text.setText("👁 Мониторинг")

    def set_monitor_trigger(self, zone_name: str):
        self._set_led_active(self.mon_led, COLORS['success'], f"👁 Триггер: {zone_name}")
        QTimer.singleShot(1500, lambda: (
            self._set_led_active(self.mon_led, COLORS['amber'], "👁 Мониторинг активен")
            if self.mon_led._state == "active" else None))

    # ── Blueprint LED API ─────────────────────────────────────────────────────
    def set_blueprint_active(self, name: str = ""):
        txt = f"🔷 Blueprint: {name}" if name else "🔷 Blueprint активен"
        self._set_led_active(self.bp_led, COLORS['accent_bright'], txt)

    def set_blueprint_idle(self):
        self._set_led_idle(self.bp_led, "🔷 Blueprint")
        self.bp_led._text.setText("🔷 Blueprint")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        log.info("MainWindow.__init__ start")
        self._debug_window = None
        self._setup_window()
        self._setup_ui()
        self._setup_statusbar()
        self._connect_engine()
        self._connect_monitor()
        self._connect_ocr()
        self._connect_global_font()
        log.info("MainWindow.__init__ complete")

    @trace_calls
    def _setup_window(self):
        self.setWindowTitle("MacroX")
        self.setMinimumSize(QSize(1350, 860))
        self.resize(QSize(1728, 980))
        self.setStyleSheet(get_app_stylesheet())
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move((geo.width() - self.width()) // 2,
                      (geo.height() - self.height()) // 2)

    def _setup_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(self._switch_page)
        root.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:transparent;")
        PAGE_NAMES = ["Макросы","Настройки","Мониторинг","Blueprint","State","Журнал"]
        self.pages = [MacrosPage(), SettingsPage(), MonitorPage(), BlueprintPage(), StatePage(), LogPage()]
        for p in self.pages:
            self.stack.addWidget(p)
        self._page_names = PAGE_NAMES
        root.addWidget(self.stack, 1)

    def _setup_statusbar(self):
        c = COLORS
        bar = self.statusBar()
        bar.setStyleSheet(f"""
            QStatusBar{{
                background:{c['bg_deep']};color:{c['text_muted']};
                border-top:1px solid {c['border']};
                font-size:{FONTS['size_xs']};padding:0 4px;
            }}
            QStatusBar QPushButton{{
                background:transparent;border:1px solid {c['border']};
                border-radius:3px;color:{c['text_muted']};
                font-size:{FONTS['size_xs']};padding:1px 8px;margin:2px 4px;
            }}
            QStatusBar QPushButton:hover{{
                background:{c['bg_hover']};color:{c['accent_bright']};
                border-color:{c['accent']};
            }}
        """)

        # ── LEFT: LED status indicator ────────────────────────────────────────
        self.status_indicator = StatusIndicator()
        bar.addWidget(self.status_indicator)

        # ── MIDDLE: OCR warmup notice (hidden until needed) ──────────────────
        self._ocr_status_lbl = QLabel("")
        self._ocr_status_lbl.setStyleSheet(
            f"color:{c['amber']};background:transparent;"
            f"font-size:{FONTS['size_xs']};padding:0 8px;")
        self._ocr_status_lbl.hide()
        bar.addWidget(self._ocr_status_lbl)

        # ── RIGHT: Debug + version ────────────────────────────────────────────
        btn_debug = QPushButton("◈ Debug")
        btn_debug.setToolTip("Открыть окно отладки с живым логом всех событий")
        btn_debug.clicked.connect(self._toggle_debug)
        bar.addPermanentWidget(btn_debug)

        sep = QLabel("|")
        sep.setStyleSheet(f"color:{c['border']};background:transparent;")
        bar.addPermanentWidget(sep)

        ver = QLabel("MacroX v0.1.0")
        ver.setStyleSheet(f"color:{c['text_muted']};background:transparent;"
                          f"font-size:{FONTS['size_xs']};padding-right:8px;")
        bar.addPermanentWidget(ver)

    def _connect_monitor(self):
        """Wire MonitorEngine signals → StatusIndicator."""
        try:
            from core.monitor_engine import monitor_signals as ms
            ms.engine_started.connect(
                lambda: self.status_indicator.set_monitor(True))
            ms.engine_stopped.connect(
                lambda: self.status_indicator.set_monitor(False))
            ms.zone_triggered.connect(
                lambda zid, name, sim: self.status_indicator.set_monitor_trigger(name))
            log.info("MonitorEngine signals connected to status bar")
        except Exception as e:
            log.error(f"Monitor connect error: {e}")

    def _connect_ocr(self):
        """Show EasyOCR download/warmup notice in statusbar."""
        try:
            from core.ocr_engine import add_easyocr_state_listener, get_easyocr_state
            # Qt signal delivers directly on main thread — no QTimer wrapper needed
            add_easyocr_state_listener(self._apply_ocr_status)
            # Apply current state immediately (warmup may have already progressed)
            st, sm = get_easyocr_state()
            if st not in ("idle", "ready"):
                self._apply_ocr_status(st, sm)
        except Exception as e:
            log.debug(f"OCR status connect: {e}")

    def _apply_ocr_status(self, state: str, msg: str):
        c = COLORS
        lbl = self._ocr_status_lbl
        if state == "downloading":
            lbl.setText("⬇ EasyOCR: скачивание моделей (~90 МБ), подождите…")
            lbl.setStyleSheet(
                f"color:{c['amber']};background:transparent;"
                f"font-size:{FONTS['size_xs']};padding:0 8px;")
            lbl.show()
        elif state == "loading":
            lbl.setText("⟳ EasyOCR: загрузка в память…")
            lbl.setStyleSheet(
                f"color:{c['amber']};background:transparent;"
                f"font-size:{FONTS['size_xs']};padding:0 8px;")
            lbl.show()
        elif state == "ready":
            lbl.setText("✓ EasyOCR готов")
            lbl.setStyleSheet(
                f"color:{c['success']};background:transparent;"
                f"font-size:{FONTS['size_xs']};padding:0 8px;")
            lbl.show()
            QTimer.singleShot(5000, lbl.hide)
        elif state == "error":
            lbl.setText(f"✗ EasyOCR: {msg[:60]}")
            lbl.setStyleSheet(
                f"color:{c['danger']};background:transparent;"
                f"font-size:{FONTS['size_xs']};padding:0 8px;")
            lbl.show()
            QTimer.singleShot(8000, lbl.hide)
        else:
            lbl.hide()

    def _connect_engine(self):
        """Wire MacroEngine signals → StatusIndicator."""
        try:
            from core.macro_engine import engine_signals
            engine_signals.macro_started.connect(self.status_indicator.set_running)
            engine_signals.macro_stopped.connect(self._on_macro_stopped)
            engine_signals.active_count_changed.connect(
                self.status_indicator.set_active_count
            )
            log.info("Engine signals connected to status indicator")
        except Exception as e:
            log.error(f"Failed to connect engine signals: {e}")

    def _connect_global_font(self):
        """When global font scale changes, rebuild app stylesheet."""
        try:
            from core.font_scale import get_global_font
            get_global_font().scale_changed.connect(self._on_global_font)
            log.info("Global font scale connected to main window")
        except Exception as e:
            log.error(f"Font connect error: {e}")

    def _on_global_font(self, level: int):
        from ui.theme import get_app_stylesheet
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont
        from core.font_scale import get_global_font, LEVELS
        # 1. Rebuild global stylesheet (all widgets that use FONTS dict)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_app_stylesheet())
        # 2. Set QApplication default font — propagates to widgets without
        #    explicit stylesheet (sidebar nav buttons, labels, etc.)
        m = get_global_font().mult()
        base_pt = max(8, round(13 * m))   # 13px ≈ 10pt baseline
        app.setFont(QFont("Segoe UI", base_pt))
        # 3. Force all top-level widgets to repaint / recalculate layout
        if app:
            for w in app.topLevelWidgets():
                w.setStyleSheet(w.styleSheet())  # no-op triggers style recalc
                w.update()
        log.info(f"App stylesheet + QFont rebuilt for font level {level}")

    def _on_macro_stopped(self, name: str):
        # set_active_count will be called right after with updated count,
        # so we just log here
        log.debug(f"Macro stopped: {name}")

    @trace_calls
    def _switch_page(self, index: int):
        self.stack.setCurrentIndex(index)
        log.info(f"Page switched to: {self._page_names[index]}")

    @trace_calls
    def _toggle_debug(self):
        if self._debug_window is None or not self._debug_window.isVisible():
            from ui.debug_window import DebugWindow
            self._debug_window = DebugWindow()
            geo = self.geometry()
            self._debug_window.move(geo.right() + 10, geo.top())
            self._debug_window.show()
        else:
            self._debug_window.close()

    def closeEvent(self, e):
        log.info("Application closing")
        if self._debug_window:
            self._debug_window.close()
        e.accept()
