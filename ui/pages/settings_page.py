"""
MacroX — Settings Page
Global settings: font scale, (future: hotkeys, profiles, etc.)
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSpacerItem, QSizePolicy,
    QComboBox, QLineEdit, QTextEdit, QFileDialog, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from ui.theme import COLORS, FONTS
from core.font_scale import get_global_font, LEVELS

log = logging.getLogger(__name__)


class FontScaleSelector(QWidget):
    """5-button scale selector used in Settings (global) and Journal (local)."""
    def __init__(self, get_scale_fn, label: str, description: str, parent=None):
        super().__init__(parent)
        self._get_scale = get_scale_fn
        c = COLORS
        self.setStyleSheet(
            f"QWidget{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:8px;}} QLabel{{background:transparent;border:none;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(8)

        hdr = QHBoxLayout()
        ttl = QLabel(label)
        ttl.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};font-weight:600;")
        desc = QLabel(description)
        desc.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        hdr.addWidget(ttl); hdr.addStretch(); hdr.addWidget(desc)
        lay.addLayout(hdr)

        # Buttons row
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self._btns: list[QPushButton] = []
        fs = self._get_scale()

        for i, lvl in enumerate(LEVELS):
            b = QPushButton(lvl["name"])
            b.setFixedHeight(36)
            b.setCheckable(True)
            b.setChecked(i == fs.level())
            b.setProperty("idx", i)
            b.setStyleSheet(self._s(i == fs.level()))
            b.clicked.connect(lambda _, idx=i: self._pick(idx))
            self._btns.append(b)
            btn_row.addWidget(b)

        lay.addLayout(btn_row)

        # Preview line
        self.preview = QLabel("Пример текста — MacroX")
        self._update_preview(fs.level())
        lay.addWidget(self.preview)

    def _pick(self, idx: int):
        fs = self._get_scale()
        fs.set_level(idx)
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._s(i == idx))
        self._update_preview(idx)

    def _update_preview(self, idx: int):
        mult = LEVELS[idx]["mult"]
        size = max(9, round(13 * mult))
        self.preview.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-size:{size}px;"
            f"background:transparent;padding-top:4px;")

    @staticmethod
    def _s(active: bool) -> str:
        c = COLORS
        if active:
            return (f"QPushButton{{background:{c['accent_dim']};color:{c['accent_bright']};"
                    f"border:2px solid {c['accent']};border-radius:6px;"
                    f"font-size:{FONTS['size_sm']};font-weight:700;padding:0 12px;}}"
                    f"QPushButton:checked{{background:{c['accent_dim']};}}")
        return (f"QPushButton{{background:{c['bg_elevated']};color:{c['text_secondary']};"
                f"border:1px solid {c['border']};border-radius:6px;"
                f"font-size:{FONTS['size_sm']};padding:0 12px;}}"
                f"QPushButton:hover{{color:{c['text_primary']};"
                f"border-color:{c['border_bright']};}}")


class SettingsSection(QWidget):
    """Titled section card."""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        c = COLORS
        self.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(10)
        hdr = QLabel(title.upper())
        hdr.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.5px;background:transparent;")
        lay.addWidget(hdr)
        self.content = QVBoxLayout()
        self.content.setSpacing(8)
        lay.addLayout(self.content)

    def add(self, w: QWidget):
        self.content.addWidget(w)


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        # React to global font changes (e.g. triggered from here)
        get_global_font().scale_changed.connect(self._on_global_font_changed)

    def _build(self):
        c = COLORS
        self.setStyleSheet(f"background:{c['bg_main']};")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Top bar
        bar = QWidget(); bar.setFixedHeight(64)
        bar.setStyleSheet(
            f"background:{c['bg_panel']};border-bottom:1px solid {c['border']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(24,0,24,0)
        tv = QVBoxLayout(); tv.setSpacing(1)
        t = QLabel("Настройки")
        t.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_xl']};"
            f"font-weight:700;background:transparent;")
        s = QLabel("Глобальные параметры приложения")
        s.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_sm']};background:transparent;")
        tv.addWidget(t); tv.addWidget(s); bl.addLayout(tv); bl.addStretch()
        root.addWidget(bar)

        # Scrollable content
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;border:none;")

        body = QWidget(); body.setStyleSheet("background:transparent;")
        bl2 = QVBoxLayout(body); bl2.setContentsMargins(28,24,28,24); bl2.setSpacing(24)

        # ── Section: Interface ────────────────────────────────────────────────
        sec_ui = SettingsSection("Интерфейс")

        global_font_card = FontScaleSelector(
            get_scale_fn = get_global_font,
            label        = "Размер шрифта",
            description  = "Применяется ко всему приложению",
        )
        sec_ui.add(global_font_card)

        note = QLabel(
            "ℹ  Размер шрифта в Журнале можно дополнительно настроить "
            "прямо на странице Журнала — он имеет приоритет над глобальным."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};"
            f"background:{c['bg_elevated']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:8px 12px;")
        sec_ui.add(note)

        bl2.addWidget(sec_ui)

        # ── Section: Monitor hotkey ──────────────────────────────────────────
        sec_mon = SettingsSection("Мониторинг экрана")
        mon_card = self._monitor_hotkey_card()
        sec_mon.add(mon_card)
        bl2.addWidget(sec_mon)

        # ── Section: OCR ─────────────────────────────────────────────────────
        sec_ocr = SettingsSection("OCR — Распознавание текста на экране")
        self._ocr_card = OcrSettingsCard()
        sec_ocr.add(self._ocr_card)
        bl2.addWidget(sec_ocr)

        # ── Future sections placeholder ───────────────────────────────────────
        for title, desc in [
            ("Профили",         "Сохранение и загрузка наборов макросов"),
            ("Запуск и память", "Автозапуск, сохранение сессии, история"),
        ]:
            sec = SettingsSection(title)
            ph = QWidget()
            ph.setFixedHeight(52)
            ph.setStyleSheet(
                f"background:{c['bg_card']};border:1px solid {c['border']};"
                f"border-radius:8px;")
            pl = QHBoxLayout(ph); pl.setContentsMargins(18,0,18,0)
            dl = QLabel(desc)
            dl.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_sm']};"
                             f"background:transparent;")
            badge = QLabel("Скоро")
            badge.setStyleSheet(
                f"color:{c['amber']};background:{c['amber_dim']};"
                f"border:1px solid {c['amber']};border-radius:3px;"
                f"padding:2px 8px;font-size:{FONTS['size_xs']};font-weight:600;")
            pl.addWidget(dl); pl.addStretch(); pl.addWidget(badge)
            sec.add(ph)
            bl2.addWidget(sec)

        bl2.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                QSizePolicy.Policy.Expanding))
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _monitor_hotkey_card(self) -> QWidget:
        """Card for monitor start/stop hotkey setting."""
        from core.font_scale import _load_settings, _save_settings
        c = COLORS
        card = QWidget()
        card.setStyleSheet(
            f"QWidget{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:8px;}} QLabel{{background:transparent;border:none;}}")
        lay = QVBoxLayout(card); lay.setContentsMargins(18,12,18,12); lay.setSpacing(10)

        hdr = QHBoxLayout()
        ttl = QLabel("Горячая клавиша: Старт / Стоп мониторинга")
        ttl.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};font-weight:600;")
        hdr.addWidget(ttl); hdr.addStretch()
        lay.addLayout(hdr)

        row = QHBoxLayout(); row.setSpacing(8)
        from PyQt6.QtWidgets import QLineEdit, QPushButton
        self._mon_hk_edit = QLineEdit()
        self._mon_hk_edit.setReadOnly(True)
        self._mon_hk_edit.setPlaceholderText("Не назначена")
        saved = _load_settings().get("monitor_hotkey","")
        self._mon_hk_edit.setText(saved)
        self._mon_hk_edit.setFixedHeight(34)
        self._mon_hk_edit.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:6px;padding:4px 10px;"
            f"color:{c['accent_bright']};font-family:{FONTS['mono']};"
            f"font-size:{FONTS['size_md']};")
        row.addWidget(self._mon_hk_edit, 1)

        assign_btn = QPushButton("🎯 Назначить")
        assign_btn.setFixedHeight(34)
        assign_btn.setStyleSheet(
            f"QPushButton{{background:{c['bg_elevated']};color:{c['text_secondary']};"
            f"border:1px solid {c['border_bright']};border-radius:6px;"
            f"font-size:{FONTS['size_sm']};padding:0 14px;}}"
            f"QPushButton:hover{{background:{c['bg_hover']};color:{c['accent_bright']};"
            f"border-color:{c['accent']};}}")
        assign_btn.clicked.connect(self._assign_monitor_hk)
        row.addWidget(assign_btn)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(34,34)
        clear_btn.setStyleSheet(
            f"QPushButton{{background:{c['danger_dim']};color:{c['danger']};"
            f"border:1px solid {c['danger']};border-radius:6px;font-size:12px;}}"
            f"QPushButton:hover{{background:{c['danger']};color:white;}}")
        clear_btn.clicked.connect(self._clear_monitor_hk)
        row.addWidget(clear_btn)
        lay.addLayout(row)

        note = QLabel("Клавиша запускает или останавливает движок мониторинга глобально.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        lay.addWidget(note)
        return card

    def _assign_monitor_hk(self):
        from ui.hotkey_capture import HotkeyCaptureDialog
        from core.font_scale import _save_settings
        dlg = HotkeyCaptureDialog(
            current_hotkey=self._mon_hk_edit.text(), parent=self)
        def _on_captured(hk: str):
            self._mon_hk_edit.setText(hk)
            _save_settings({"monitor_hotkey": hk})
            self._register_monitor_hk(hk)
        dlg.hotkey_captured.connect(_on_captured)
        dlg.exec()

    def _clear_monitor_hk(self):
        from core.font_scale import _save_settings
        self._mon_hk_edit.clear()
        _save_settings({"monitor_hotkey": ""})

    def _register_monitor_hk(self, hk: str):
        """Register global hotkey that toggles monitor engine via MacroEngine."""
        try:
            from core.monitor_engine import get_monitor_engine
            get_monitor_engine().register_hotkey(hk)
        except Exception as e:
            import logging; logging.getLogger(__name__).error(f"register hk: {e}")

    def _on_global_font_changed(self, level: int):
        """When global font changes, rebuild this page's stylesheet."""
        from ui.theme import FONTS, get_app_stylesheet
        # Just trigger a repaint — stylesheets re-read FONTS on next paint
        self.setStyleSheet(f"background:{COLORS['bg_main']};")
        log.info(f"SettingsPage: global font level → {level}")


# ═══════════════════════════════════════════════════════════════════════════════
# OCR Settings Card
# ═══════════════════════════════════════════════════════════════════════════════
class _StatusChip(QLabel):
    """Small coloured pill showing OK / Error / Unknown."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setStyleSheet("border-radius:4px;padding:0 8px;font-size:11px;font-weight:700;")
        self.set_unknown()

    def set_ok(self, text: str = "✓  Установлен"):
        c = COLORS
        self.setText(text)
        self.setStyleSheet(
            f"border-radius:4px;padding:0 8px;font-size:11px;font-weight:700;"
            f"color:{c['success']};background:{c['success_dim']};border:1px solid {c['success']};")

    def set_error(self, text: str = "✗  Не найден"):
        c = COLORS
        self.setText(text)
        self.setStyleSheet(
            f"border-radius:4px;padding:0 8px;font-size:11px;font-weight:700;"
            f"color:{c['danger']};background:{c['danger_dim']};border:1px solid {c['danger']};")

    def set_unknown(self, text: str = "?  Проверяется…"):
        c = COLORS
        self.setText(text)
        self.setStyleSheet(
            f"border-radius:4px;padding:0 8px;font-size:11px;font-weight:700;"
            f"color:{c['text_muted']};background:{c['bg_elevated']};border:1px solid {c['border']};")

    def set_busy(self, text: str = "⟳  Устанавливается…"):
        c = COLORS
        self.setText(text)
        self.setStyleSheet(
            f"border-radius:4px;padding:0 8px;font-size:11px;font-weight:700;"
            f"color:{c['amber']};background:{c['amber_dim']};border:1px solid {c['amber']};")


class OcrSettingsCard(QWidget):
    """
    Full OCR management card:
      - Status chips for OpenCV / Tesseract / EasyOCR
      - Install buttons with live output log
      - Tesseract binary path (Windows)
      - Preferred engine selector
      - Test panel: capture region → compare both engines
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        c = COLORS
        self.setStyleSheet(
            f"QWidget{{background:{c['bg_card']};border:1px solid {c['border']};"
            f"border-radius:10px;}} QLabel{{background:transparent;border:none;}}")
        self._build()
        self._test_capture = None   # PIL image for test
        # Probe status after a short delay (avoid blocking startup)
        QTimer.singleShot(400, self._refresh_status)

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        c = COLORS
        root = QVBoxLayout(self); root.setContentsMargins(20,16,20,16); root.setSpacing(14)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QLabel("OCR — Распознавание чисел на иконках бафов")
        hdr.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};font-weight:700;")
        root.addWidget(hdr)

        note = QLabel(
            "OCR позволяет читать числовые значения прямо с иконок бафов (стаки, кулдаун, HP).\n"
            "Поддерживаются два движка: Tesseract (быстрый) и EasyOCR (точнее на игровых шрифтах).")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        root.addWidget(note)

        root.addWidget(self._hsep())

        # ── Status grid ───────────────────────────────────────────────────────
        root.addWidget(self._section_lbl("КОМПОНЕНТЫ"))

        # OpenCV row
        cv_row = self._row()
        cv_row.addWidget(self._lbl("OpenCV", bold=True, w=110))
        self._chip_cv = _StatusChip(); cv_row.addWidget(self._chip_cv)
        cv_row.addStretch()
        self._btn_cv = self._action_btn("pip install", self._install_cv)
        cv_row.addWidget(self._btn_cv)
        root.addLayout(cv_row)

        # Tesseract-program row
        tprog_row = self._row()
        tprog_row.addWidget(self._lbl("Tesseract  (программа)", bold=True, w=180))
        self._chip_tprog = _StatusChip(); tprog_row.addWidget(self._chip_tprog)
        tprog_row.addStretch()
        dl_btn = self._action_btn("⬇ Скачать", self._open_tesseract_download)
        dl_btn.setToolTip("Открыть страницу загрузки Tesseract-OCR в браузере")
        tprog_row.addWidget(dl_btn)
        root.addLayout(tprog_row)

        # Tesseract path (Windows)
        path_row = self._row()
        path_row.addWidget(self._lbl("Путь к tesseract.exe:", w=170))
        self._tess_path = QLineEdit()
        self._tess_path.setPlaceholderText(
            r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        self._tess_path.setFixedHeight(30)
        self._tess_path.setStyleSheet(
            f"background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:5px;padding:0 8px;color:{c['text_secondary']};"
            f"font-size:{FONTS['size_xs']};font-family:{FONTS['mono']};")
        path_row.addWidget(self._tess_path, 1)
        browse_btn = self._action_btn("📁", self._browse_tesseract)
        browse_btn.setFixedWidth(36)
        path_row.addWidget(browse_btn)
        apply_btn = self._action_btn("Применить", self._apply_tess_path)
        path_row.addWidget(apply_btn)
        root.addLayout(path_row)

        # pytesseract row
        tpy_row = self._row()
        tpy_row.addWidget(self._lbl("pytesseract  (Python)", bold=True, w=180))
        self._chip_tpy = _StatusChip(); tpy_row.addWidget(self._chip_tpy)
        tpy_row.addStretch()
        self._btn_tpy = self._action_btn("pip install", self._install_pytesseract)
        tpy_row.addWidget(self._btn_tpy)
        root.addLayout(tpy_row)

        # EasyOCR row
        easy_row = self._row()
        easy_row.addWidget(self._lbl("EasyOCR  (Python + модели)", bold=True, w=220))
        self._chip_easy = _StatusChip(); easy_row.addWidget(self._chip_easy)
        easy_row.addStretch()
        self._btn_easy = self._action_btn("pip install", self._install_easyocr)
        easy_row.addWidget(self._btn_easy)
        root.addLayout(easy_row)

        # EasyOCR "fix torch" button row
        fix_row = self._row()
        fix_lbl = self._lbl("Проблема с DLL / несовместимость torch?", w=280)
        fix_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};")
        fix_row.addWidget(fix_lbl)
        self._btn_fix_torch = self._action_btn(
            "🔧  Исправить EasyOCR (откат torch)", self._fix_easyocr_torch,
            bg=COLORS['amber_dim'], fg=COLORS['amber'])
        self._btn_fix_torch.setToolTip(
            "Удалит текущие версии torch/torchvision/easyocr "
            "и установит torch==2.8.0 + torchvision==0.23.0 + easyocr "
            "(проверенная совместимая комбинация)")
        fix_row.addWidget(self._btn_fix_torch)
        fix_row.addStretch()
        root.addLayout(fix_row)

        # EasyOCR DLL hint (hidden by default, shown on WinError 1114)
        self._easy_hint = QLabel("")
        self._easy_hint.setWordWrap(True)
        self._easy_hint.setStyleSheet(
            f"color:{COLORS['amber']};font-size:{FONTS['size_xs']};"
            f"background:{COLORS['amber_dim']};border:1px solid {COLORS['amber']};"
            f"border-radius:6px;padding:8px 12px;")
        self._easy_hint.hide()
        root.addWidget(self._easy_hint)

        # Install progress / log
        self._install_log = QTextEdit()
        self._install_log.setReadOnly(True)
        self._install_log.setFixedHeight(80)
        self._install_log.setStyleSheet(
            f"background:{c['bg_deep']};border:1px solid {c['border']};"
            f"border-radius:6px;color:{c['text_secondary']};"
            f"font-family:{FONTS['mono']};font-size:{FONTS['size_xs']};")
        self._install_log.setPlaceholderText("Здесь появится вывод установки…")
        self._install_log.hide()
        root.addWidget(self._install_log)

        root.addWidget(self._hsep())

        # ── EasyOCR warmup status banner ──────────────────────────────────────
        self._warmup_banner = QLabel("")
        self._warmup_banner.setWordWrap(True)
        self._warmup_banner.setFixedHeight(40)
        self._warmup_banner.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._warmup_banner.setStyleSheet(
            f"color:{COLORS['amber']};font-size:{FONTS['size_xs']};"
            f"background:{COLORS['amber_dim']};border:1px solid {COLORS['amber']};"
            f"border-radius:6px;padding:0 12px;font-weight:600;")
        self._warmup_banner.hide()
        root.addWidget(self._warmup_banner)
        # Subscribe to EasyOCR state changes
        try:
            from core.ocr_engine import add_easyocr_state_listener, get_easyocr_state
            # Qt signal — delivered on main thread automatically
            add_easyocr_state_listener(self._apply_easyocr_state)
            # Catch up if warmup already started before this card was built
            st, sm = get_easyocr_state()
            if st not in ("idle",):
                self._apply_easyocr_state(st, sm)
        except Exception:
            pass

        # ── Preferred engine ──────────────────────────────────────────────────
        root.addWidget(self._section_lbl("АКТИВНЫЙ ДВИЖОК"))
        eng_row = self._row()
        eng_row.addWidget(self._lbl("Предпочтительный движок:", w=200))
        self._engine_cb = QComboBox()
        self._engine_cb.addItems([
            "Авто (Tesseract → EasyOCR)",
            "Tesseract",
            "EasyOCR",
        ])
        self._engine_cb.setFixedHeight(30)
        self._engine_cb.setStyleSheet(
            f"QComboBox{{background:{c['bg_panel']};border:1px solid {c['border']};"
            f"border-radius:5px;padding:0 8px;color:{c['text_secondary']};"
            f"font-size:{FONTS['size_xs']};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}")
        self._engine_cb.currentIndexChanged.connect(self._save_engine_pref)

        self._active_chip = _StatusChip()
        eng_row.addWidget(self._engine_cb)
        eng_row.addWidget(self._active_chip)
        refresh_btn = self._action_btn("🔄 Проверить", self._refresh_status)
        eng_row.addWidget(refresh_btn)
        eng_row.addStretch()
        root.addLayout(eng_row)

        root.addWidget(self._hsep())

        # ── Test panel ────────────────────────────────────────────────────────
        root.addWidget(self._section_lbl("ТЕСТ РАСПОЗНАВАНИЯ"))

        test_note = QLabel(
            "Выделите область на экране с числом (например иконку бафа со значением) — "
            "оба движка попробуют прочитать его, результаты отобразятся ниже для сравнения.")
        test_note.setWordWrap(True)
        test_note.setStyleSheet(f"color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        root.addWidget(test_note)

        test_btn_row = self._row()
        self._btn_capture_test = self._action_btn(
            "⊹ Захватить область для теста", self._capture_test_region,
            bg=c['accent_dim'], fg=c['accent_bright'])
        test_btn_row.addWidget(self._btn_capture_test)
        self._btn_run_test = self._action_btn(
            "▶ Запустить тест", self._run_test,
            bg=c['bg_elevated'], fg=c['text_secondary'])
        self._btn_run_test.setEnabled(False)
        test_btn_row.addWidget(self._btn_run_test)
        test_btn_row.addStretch()
        root.addLayout(test_btn_row)

        # Preview + results side by side
        preview_row = self._row()
        preview_row.setSpacing(12)

        # Captured image preview
        self._test_preview = QLabel("Нет изображения")
        self._test_preview.setFixedSize(120, 60)
        self._test_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._test_preview.setStyleSheet(
            f"background:{c['bg_deep']};border:1px solid {c['border']};"
            f"border-radius:6px;color:{c['text_muted']};font-size:{FONTS['size_xs']};")
        preview_row.addWidget(self._test_preview)

        # Results
        results_w = QWidget(); results_w.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(results_w); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)

        self._res_tess = self._result_row("Tesseract:", "—")
        self._res_easy = self._result_row("EasyOCR:", "—")
        rl.addLayout(self._res_tess["layout"])
        rl.addLayout(self._res_easy["layout"])
        rl.addStretch()
        preview_row.addWidget(results_w, 1)
        root.addLayout(preview_row)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _refresh_status(self):
        from core.ocr_engine import get_ocr_engine
        st = get_ocr_engine().status()

        # OpenCV
        if st["opencv_available"]:
            self._chip_cv.set_ok(f"✓  {st['opencv_msg']}")
        else:
            self._chip_cv.set_error(f"✗  {st['opencv_msg']}")

        # Tesseract binary (probe separately)
        try:
            import pytesseract
            from core.ocr_engine import _load_ocr_settings
            path = _load_ocr_settings().get("tesseract_path","")
            if path: pytesseract.pytesseract.tesseract_cmd = path
            ver = pytesseract.get_tesseract_version()
            self._chip_tprog.set_ok(f"✓  Tesseract {ver}")
        except Exception:
            self._chip_tprog.set_error("✗  Не найден — скачайте установщик")

        # pytesseract python
        if st["tesseract_available"]:
            self._chip_tpy.set_ok(f"✓  {st['tesseract_msg']}")
        else:
            self._chip_tpy.set_error(f"✗  {st['tesseract_msg']}")

        # EasyOCR
        if st["easyocr_available"]:
            self._chip_easy.set_ok(f"✓  {st['easyocr_msg']}")
            self._easy_hint.hide()
        else:
            msg = st["easyocr_msg"]
            self._chip_easy.set_error(f"✗  EasyOCR ошибка: {msg[:80]}")
            if "1114" in msg or "DLL" in msg or "c10.dll" in msg:
                hint_lines = [
                    "Ошибка DLL (WinError 1114) — проблема PyTorch, не MacroX.",
                    "",
                    "Решение 1: установите Visual C++ Redistributable 2022 (x64)",
                    "  https://aka.ms/vs/17/release/vc_redist.x64.exe",
                    "",
                    "Решение 2: PyTorch не поддерживает Python 3.13 официально.",
                    "  Используйте Tesseract — он уже работает.",
                ]
                self._easy_hint.setText("\n".join(hint_lines))
                self._easy_hint.show()
            else:
                self._easy_hint.hide()

        # Preferred engine combo
        pref_map = {"auto":0,"tesseract":1,"easyocr":2}
        self._engine_cb.blockSignals(True)
        self._engine_cb.setCurrentIndex(pref_map.get(st["preferred"], 0))
        self._engine_cb.blockSignals(False)

        # Active engine chip
        eng = st["active_engine"]
        if eng == "none":
            self._active_chip.set_error("Нет движка")
        else:
            self._active_chip.set_ok(f"▶  {eng}")

        # Restore saved path
        from core.ocr_engine import _load_ocr_settings
        saved_path = _load_ocr_settings().get("tesseract_path","")
        if saved_path and not self._tess_path.text():
            self._tess_path.setText(saved_path)

    def _apply_easyocr_state(self, state: str, msg: str):
        c = COLORS
        if state == "downloading":
            self._warmup_banner.setText(
                "⬇  " + msg)
            self._warmup_banner.setStyleSheet(
                f"color:{c['amber']};font-size:{FONTS['size_xs']};"
                f"background:{c['amber_dim']};border:1px solid {c['amber']};"
                f"border-radius:6px;padding:0 12px;font-weight:600;")
            self._warmup_banner.show()
        elif state == "loading":
            self._warmup_banner.setText("⟳  " + msg)
            self._warmup_banner.show()
        elif state == "ready":
            self._warmup_banner.setText("✓  EasyOCR готов — модели загружены, OCR работает быстро")
            self._warmup_banner.setStyleSheet(
                f"color:{c['success']};font-size:{FONTS['size_xs']};"
                f"background:{c['success_dim']};border:1px solid {c['success']};"
                f"border-radius:6px;padding:0 12px;font-weight:600;")
            self._warmup_banner.show()
            QTimer.singleShot(6000, self._warmup_banner.hide)
            self._refresh_status()
        elif state == "error":
            self._warmup_banner.setText("✗  EasyOCR ошибка: " + msg[:120])
            self._warmup_banner.setStyleSheet(
                f"color:{c['danger']};font-size:{FONTS['size_xs']};"
                f"background:{c['danger_dim']};border:1px solid {c['danger']};"
                f"border-radius:6px;padding:0 12px;font-weight:600;")
            self._warmup_banner.show()
        else:
            self._warmup_banner.hide()

    def _install_cv(self):
        self._start_install("opencv-python", "OpenCV")

    def _install_pytesseract(self):
        self._start_install("pytesseract", "pytesseract")

    def _install_easyocr(self):
        self._start_install("easyocr", "EasyOCR")

    def _fix_easyocr_torch(self):
        from core.ocr_engine import get_ocr_engine
        self._btn_fix_torch.setEnabled(False)
        self._btn_fix_torch.setText("⟳  Выполняется...")
        self._install_log.show()
        self._install_log.clear()
        self._install_log.append(
            "Исправление EasyOCR: откат torch до совместимой версии..." + "\n" +
            "Это может занять 2-5 минут." + "\n")
        self._easy_hint.hide()

        def _done(ok, output):
            self._install_log.append(output[-2000:])
            self._btn_fix_torch.setEnabled(True)
            label = "✓  Готово" if ok else "🔧  Исправить EasyOCR (откат torch)"
            self._btn_fix_torch.setText(label)
            QTimer.singleShot(600, self._refresh_status)

        get_ocr_engine().fix_easyocr_torch(_done)

    def _start_install(self, package: str, display_name: str):
        from core.ocr_engine import get_ocr_engine
        chip_map = {
            "opencv-python": self._chip_cv,
            "pytesseract":   self._chip_tpy,
            "easyocr":       self._chip_easy,
        }
        chip = chip_map.get(package)
        if chip: chip.set_busy(f"⟳  Устанавливается…")

        self._install_log.show()
        self._install_log.clear()
        self._install_log.setPlaceholderText("")
        self._install_log.append(f"→  pip install {package}\n")

        def _done(ok: bool, output: str):
            self._install_log.append(output[-1200:])
            # Re-inject user site-packages so newly installed module is importable
            # without restarting the app
            try:
                import site, sys
                user_site = site.getusersitepackages()
                if user_site and user_site not in sys.path:
                    sys.path.insert(0, user_site)
                # Force reimport of freshly installed packages
                import importlib
                for mod in ("pytesseract", "easyocr", "cv2"):
                    try: importlib.import_module(mod)
                    except ImportError: pass
            except Exception: pass
            QTimer.singleShot(400, self._refresh_status)

        get_ocr_engine()._run_pip([package], _done)

    def _open_tesseract_download(self):
        import webbrowser
        webbrowser.open("https://github.com/UB-Mannheim/tesseract/wiki")

    def _browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Найти tesseract.exe",
            r"C:\Program Files\Tesseract-OCR",
            "Tesseract (tesseract.exe);;All files (*)")
        if path:
            self._tess_path.setText(path)
            self._apply_tess_path()

    def _apply_tess_path(self):
        from core.ocr_engine import get_ocr_engine
        path = self._tess_path.text().strip()
        get_ocr_engine().set_tesseract_path(path)
        QTimer.singleShot(200, self._refresh_status)

    def _save_engine_pref(self, idx: int):
        from core.ocr_engine import get_ocr_engine
        eng_map = {0:"auto", 1:"tesseract", 2:"easyocr"}
        get_ocr_engine().set_preferred(eng_map[idx])
        QTimer.singleShot(100, self._refresh_status)

    def _capture_test_region(self):
        from ui.widgets.region_selector import RegionSelectorOverlay
        self._sel = RegionSelectorOverlay(mode="rect")
        self._sel.region_selected.connect(self._on_test_region)

    def _on_test_region(self, x, y, w, h):
        from core.monitor_engine import capture_region
        img = capture_region([x, y, w, h])
        if not img:
            return
        self._test_capture = img
        # Show preview
        try:
            from PyQt6.QtGui import QPixmap, QImage
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qimg = QImage.fromData(buf.getvalue())
            px = QPixmap.fromImage(qimg).scaled(
                120, 60,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._test_preview.setPixmap(px)
        except Exception as e:
            self._test_preview.setText(f"{w}×{h}")
        self._btn_run_test.setEnabled(True)

    def _run_test(self):
        if not self._test_capture:
            return
        from core.ocr_engine import get_ocr_engine
        c = COLORS

        self._res_tess["value"].setText("⟳ …")
        self._res_easy["value"].setText("⟳ …")

        def _do():
            results = get_ocr_engine().test_image(self._test_capture)
            # Tesseract result
            t_val = results.get("tesseract")
            t_err = results["errors"].get("tesseract")
            if t_val is not None:
                self._res_tess["value"].setText(
                    f'"{t_val}"' if t_val else "(пусто)")
                self._res_tess["value"].setStyleSheet(
                    f"color:{c['success']};font-size:{FONTS['size_md']};"
                    f"font-weight:700;font-family:{FONTS['mono']};background:transparent;")
            else:
                self._res_tess["value"].setText(f"Ошибка: {t_err}")
                self._res_tess["value"].setStyleSheet(
                    f"color:{c['danger']};font-size:{FONTS['size_xs']};background:transparent;")

            # EasyOCR result
            e_val = results.get("easyocr")
            e_err = results["errors"].get("easyocr")
            if e_val is not None:
                self._res_easy["value"].setText(
                    f'"{e_val}"' if e_val else "(пусто)")
                self._res_easy["value"].setStyleSheet(
                    f"color:{c['success']};font-size:{FONTS['size_md']};"
                    f"font-weight:700;font-family:{FONTS['mono']};background:transparent;")
            else:
                self._res_easy["value"].setText(f"Ошибка: {e_err}")
                self._res_easy["value"].setStyleSheet(
                    f"color:{c['danger']};font-size:{FONTS['size_xs']};background:transparent;")

        import threading
        threading.Thread(target=_do, daemon=True).start()

    # ── Widget helpers ────────────────────────────────────────────────────────
    def _row(self) -> QHBoxLayout:
        l = QHBoxLayout(); l.setSpacing(8); l.setContentsMargins(0,0,0,0)
        return l

    def _lbl(self, text: str, bold: bool = False, w: int = 0) -> QLabel:
        l = QLabel(text)
        style = (f"color:{COLORS['text_secondary']};font-size:{FONTS['size_sm']};"
                 f"background:transparent;")
        if bold: style += "font-weight:600;"
        l.setStyleSheet(style)
        if w: l.setFixedWidth(w)
        return l

    def _section_lbl(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:{FONTS['size_xs']};"
            f"font-weight:700;letter-spacing:1.2px;background:transparent;")
        return l

    def _hsep(self) -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            f"background:{COLORS['border']};max-height:1px;border:none;")
        return f

    def _action_btn(self, text: str, slot, bg: str = None, fg: str = None) -> QPushButton:
        c = COLORS
        bg = bg or c['bg_elevated']; fg = fg or c['text_secondary']
        b = QPushButton(text); b.setFixedHeight(30)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg};"
            f"border-radius:5px;font-size:{FONTS['size_xs']};padding:0 12px;}}"
            f"QPushButton:hover{{background:{fg};color:white;}}"
            f"QPushButton:disabled{{opacity:0.4;}}")
        b.clicked.connect(slot)
        return b

    def _result_row(self, label: str, default: str) -> dict:
        c = COLORS
        lay = QHBoxLayout(); lay.setSpacing(10); lay.setContentsMargins(0,0,0,0)
        lbl = QLabel(label); lbl.setFixedWidth(90)
        lbl.setStyleSheet(
            f"color:{c['text_muted']};font-size:{FONTS['size_xs']};background:transparent;")
        val = QLabel(default)
        val.setStyleSheet(
            f"color:{c['text_primary']};font-size:{FONTS['size_md']};"
            f"font-weight:700;font-family:{FONTS['mono']};background:transparent;")
        lay.addWidget(lbl); lay.addWidget(val); lay.addStretch()
        return {"layout": lay, "value": val}
