"""
MacroX — Entry point.
Splash screen shows immediately, heavy non-UI init runs in background thread,
MainWindow is created safely on the main thread via Qt signal.
"""
import sys, os, threading
import logging
logging.basicConfig(level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-8s  %(name)s  —  %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger("main")
log.info(f"MacroX starting. Python: {sys.executable}  v{sys.version.split()[0]}")

try:
    from core.deps import ensure_deps
    missing = ensure_deps()
    if missing:
        log.error(f"Could not install: {missing}")
except Exception as e:
    log.error(f"Dep check failed: {e}")

try:
    from core.logger import setup_logging
    setup_logging()
    log = logging.getLogger("main")
    log.info("Logging system initialized")
except Exception as e:
    print(f"Logger init failed: {e}")

try:
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore    import QTimer, QObject, pyqtSignal

    app = QApplication(sys.argv)
    app.setApplicationName("MacroX")
    app.setApplicationVersion("0.1.0")
    log.info("QApplication created")

    # ── Bridge: safely calls _create_window on the main thread ───────────────
    class _Bridge(QObject):
        ready = pyqtSignal()
        failed = pyqtSignal(str, str)   # (err_repr, traceback)

    _bridge = _Bridge()

    # ── Show splash immediately ───────────────────────────────────────────────
    from ui.splash import MacroXSplash, splash_signals
    splash = MacroXSplash()
    splash.show()
    app.processEvents()

    _window = None

    def _show_error(err_repr: str, tb_str: str):
        """Called on main thread when any init step fails."""
        try: splash.close()
        except Exception: pass
        from ui.error_handler import show_startup_error
        show_startup_error(Exception(err_repr), tb_str)
        app.quit()

    def _create_window():
        import traceback as _tb
        global _window
        try:
            splash_signals.step.emit("Построение интерфейса…")
            app.processEvents()
            from ui.main_window import MainWindow
            _window = MainWindow()
            splash_signals.step.emit("Готово!")
            splash_signals.done.emit()
            QTimer.singleShot(700, _window.show)
            log.info("MainWindow created")
        except Exception as e:
            tb = _tb.format_exc()
            log.critical(f"MainWindow error: {e}", exc_info=True)
            _bridge.failed.emit(repr(e), tb)

    _bridge.ready.connect(_create_window)
    _bridge.failed.connect(_show_error)

    # ── Watchdog: if init stalls > 90s, show error instead of hanging ────────
    import traceback as _tb_mod
    _watchdog_done = [False]

    def _watchdog_fired():
        if not _watchdog_done[0] and _window is None:
            tb = (
                "TimeoutError: MacroX не смог загрузиться за 90 секунд.\n\n"
                "Возможные причины:\n"
                "  • EasyOCR скачивает модели (~90 МБ) при первом запуске — дождитесь\n"
                "  • Один из модулей завис при инициализации\n"
                "  • Нет доступа к сети при первом запуске\n\n"
                "Совет: если проблема повторяется, отключите EasyOCR в Настройках → OCR"
            )
            _bridge.failed.emit("TimeoutError: превышено время ожидания загрузки (90с)", tb)

    _watchdog = QTimer()
    _watchdog.setSingleShot(True)
    _watchdog.timeout.connect(_watchdog_fired)
    _watchdog.start(90_000)

    # ── Background thread: only non-UI init ───────────────────────────────────
    def _load():
        import traceback as _tb_local
        try:
            splash_signals.step.emit("Запуск движка макросов…")
            from core.macro_engine import get_engine
            engine = get_engine()
            engine.start()

            splash_signals.step.emit("Запуск движка мониторинга…")
            from core.monitor_engine import get_monitor_engine
            monitor_engine = get_monitor_engine()
            monitor_engine.load_hotkey_from_settings()
            splash_signals.step.emit("Инициализация pipeline…")
            from core.action_pipeline import get_pipeline
            get_pipeline()   # прогреть рабочий поток

            splash_signals.step.emit("Прогрев OCR (фон)…")
            try:
                from core.ocr_engine import warmup_easyocr_async
                warmup_easyocr_async()
            except Exception as _e:
                log.debug(f"EasyOCR warmup skipped: {_e}")

            _watchdog_done[0] = True
            _bridge.ready.emit()

        except Exception as e:
            _watchdog_done[0] = True
            tb = _tb_local.format_exc()
            log.critical(f"Background load error: {e}\n{tb}")
            splash_signals.step.emit(f"Ошибка: {e}")
            _bridge.failed.emit(repr(e), tb)

    threading.Thread(target=_load, daemon=True).start()

    exit_code = app.exec()

    try:
        from core.macro_engine    import get_engine
        from core.monitor_engine  import get_monitor_engine
        from core.action_pipeline import get_pipeline
        get_engine().stop()
        get_monitor_engine().stop()
        get_pipeline().stop()
        log.info("Clean shutdown complete")
    except Exception as e:
        log.error(f"Shutdown error: {e}")

    sys.exit(exit_code)

except Exception as e:
    import traceback as _tb_outer
    tb = _tb_outer.format_exc()
    log.critical(f"Fatal startup error: {e}\n{tb}")
    try:
        from ui.error_handler import show_startup_error
        show_startup_error(e, tb)
    except Exception:
        # Absolute fallback if even error_handler fails
        print(f"FATAL: {e}\n{tb}")
        input("Press Enter to exit...")
    sys.exit(1)
