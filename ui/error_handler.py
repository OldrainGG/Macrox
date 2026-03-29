"""
MacroX — Startup Error Handler

Shown when main.py crashes during startup instead of hanging on splash.
Uses a local knowledge base — no internet or API required.

Usage:
    from ui.error_handler import show_startup_error
    show_startup_error(exception, traceback_string)
"""
import sys, re, os
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QWidget, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui  import QFont, QColor, QPalette

# ── Local knowledge base ──────────────────────────────────────────────────────
# (regex_pattern, title, fix_steps, severity)
_KB = [
    (r"ModuleNotFoundError.*PyQt6",
     "PyQt6 не установлен",
     ["pip install PyQt6",
      "Или запустите fix_and_run.bat — он установит зависимости автоматически"],
     "error"),

    (r"ModuleNotFoundError.*pynput",
     "pynput не установлен",
     ["pip install pynput"], "error"),

    (r"ModuleNotFoundError.*cv2",
     "OpenCV не установлен",
     ["pip install opencv-python"], "error"),

    (r"ModuleNotFoundError.*mss",
     "mss не установлен",
     ["pip install mss"], "error"),

    (r"ModuleNotFoundError.*PIL|ModuleNotFoundError.*Pillow",
     "Pillow не установлен",
     ["pip install Pillow"], "error"),

    (r"ModuleNotFoundError.*numpy",
     "numpy не установлен",
     ["pip install numpy"], "error"),

    (r"ModuleNotFoundError.*easyocr",
     "EasyOCR не установлен",
     ["pip install easyocr",
      "При ошибке DLL: в Настройках → OCR нажмите «Исправить EasyOCR»"],
     "error"),

    (r"ModuleNotFoundError.*pytesseract",
     "pytesseract не установлен",
     ["pip install pytesseract",
      "Также нужна программа Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"],
     "error"),

    (r"ModuleNotFoundError:.*'(\w+)'",
     "Отсутствует Python-модуль",
     ["pip install <имя из ошибки выше>",
      "Или: pip install -r requirements.txt"],
     "error"),

    (r"WinError 1114|c10\.dll|torch.*DLL|OSError.*DLL",
     "Ошибка DLL — проблема torch/CUDA",
     ["Установите Visual C++ Redistributable 2022 x64:",
      "  https://aka.ms/vs/17/release/vc_redist.x64.exe",
      "Или откатите torch: pip uninstall torch torchvision -y",
      "  затем: pip install torch==2.8.0 torchvision==0.23.0"],
     "error"),

    (r"WinError 126|WinError 193",
     "Ошибка загрузки DLL",
     ["Установите Visual C++ Redistributable 2022 x64:",
      "  https://aka.ms/vs/17/release/vc_redist.x64.exe"],
     "error"),

    (r"SyntaxError|f-string|unexpected.*token",
     "Несовместимая версия Python",
     ["MacroX требует Python 3.10+",
      "Проверьте: python --version",
      "Скачайте Python 3.12: https://www.python.org/downloads/"],
     "error"),

    (r"PermissionError|Access is denied",
     "Нет прав доступа",
     ["Запустите fix_and_run.bat от имени Администратора",
      "Или установите вручную: pip install --user <пакет>"],
     "warning"),

    (r"json\.decoder\.JSONDecodeError",
     "Повреждён файл настроек",
     ["Удалите macrox/config/settings.json — он создастся заново при следующем запуске"],
     "warning"),

    (r"CUDA|RuntimeError.*cuda",
     "Ошибка CUDA / GPU",
     ["MacroX работает без GPU. Установите CPU-версию torch:",
      "  pip install torch --index-url https://download.pytorch.org/whl/cpu"],
     "warning"),

    (r"ImportError|cannot import name",
     "Ошибка импорта модуля",
     ["Устаревшая версия пакета. Попробуйте:",
      "  pip install --upgrade <пакет>",
      "Или запустите fix_and_run.bat"],
     "error"),
]

_C = {
    "bg":      "#0F1117", "panel":  "#151820", "card":   "#1A1E2A",
    "border":  "#252A3A", "text":   "#E8ECF4", "muted":  "#4A5068",
    "accent":  "#3D8EF0", "error":  "#E74C3C", "warn":   "#F0A030",
    "success": "#2ECC71", "code":   "#0A0B0F",
}


def _diagnose(tb: str) -> list[dict]:
    results = []
    for pattern, title, fixes, severity in _KB:
        if re.search(pattern, tb, re.IGNORECASE):
            mod_m = re.search(r"ModuleNotFoundError.*?'(\w+)'", tb)
            mod   = mod_m.group(1) if mod_m else "module"
            steps = [s.replace("<имя из ошибки выше>", mod) for s in fixes]
            results.append({"title": title, "fixes": steps, "severity": severity})
            if len(results) >= 3:
                break
    return results


class StartupErrorDialog(QDialog):
    def __init__(self, error: Exception, tb_str: str):
        super().__init__(None)
        self._tb   = tb_str
        self._diag = _diagnose(tb_str)
        self.setWindowTitle("MacroX — Ошибка запуска")
        self.setMinimumSize(660, 540)
        self.setStyleSheet(f"""
            QDialog   {{ background:{_C['bg']};   color:{_C['text']}; }}
            QLabel    {{ background:transparent; color:{_C['text']}; }}
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:{_C['panel']}; width:6px; border-radius:3px; }}
            QScrollBar::handle:vertical {{ background:{_C['border']}; border-radius:3px; min-height:20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self._build(error)

    def _build(self, err: Exception):
        c = _C
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header
        hdr = QWidget(); hdr.setFixedHeight(62)
        hdr.setStyleSheet(f"background:{c['panel']};border-bottom:1px solid {c['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20,0,20,0)
        icon_l = QLabel("⚠"); icon_l.setStyleSheet(f"color:{c['error']};font-size:26px;")
        ttl    = QLabel("Ошибка запуска MacroX")
        ttl.setStyleSheet(f"color:{c['text']};font-size:17px;font-weight:700;")
        hl.addWidget(icon_l); hl.addWidget(ttl); hl.addStretch()
        root.addWidget(hdr)

        # Scroll body
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); body.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(body); lay.setContentsMargins(20,14,20,14); lay.setSpacing(12)

        # Error summary
        card = self._card()
        cl = QVBoxLayout(card); cl.setContentsMargins(14,10,14,10); cl.setSpacing(4)
        el = QLabel(f"🔴  {type(err).__name__}: {str(err)[:240]}")
        el.setWordWrap(True)
        el.setStyleSheet(f"color:{c['error']};font-size:12px;font-weight:600;")
        cl.addWidget(el); lay.addWidget(card)

        # Diagnoses
        if self._diag:
            lay.addWidget(self._sect("ВОЗМОЖНЫЕ ПРИЧИНЫ И РЕШЕНИЯ"))
            for d in self._diag:
                lay.addWidget(self._diag_card(d))
        else:
            nl = QLabel("Автоматическая диагностика не дала результата.\nСм. полный лог ниже.")
            nl.setWordWrap(True)
            nl.setStyleSheet(f"color:{c['muted']};font-size:11px;")
            lay.addWidget(nl)

        # General tips
        lay.addWidget(self._sect("ОБЩИЕ СОВЕТЫ"))
        tc = self._card()
        tl = QVBoxLayout(tc); tl.setContentsMargins(14,10,14,10); tl.setSpacing(3)
        for tip in [
            "1.  Запустите fix_and_run.bat — он автоматически устанавливает зависимости",
            "2.  Убедитесь что Python 3.10+ установлен и прописан в PATH",
            "3.  Запустите fix_and_run.bat от имени Администратора (ПКМ → Запуск от администратора)",
            "4.  При первом запуске нужен интернет для скачивания пакетов",
            "5.  Скопируйте текст ошибки и обратитесь к разработчику",
        ]:
            ll = QLabel(tip)
            ll.setStyleSheet(f"color:{c['text']};font-size:11px;")
            tl.addWidget(ll)
        lay.addWidget(tc)

        # Full traceback
        lay.addWidget(self._sect("ПОЛНЫЙ ЛОГ ОШИБКИ"))
        tb_w = QTextEdit(); tb_w.setReadOnly(True); tb_w.setPlainText(self._tb)
        tb_w.setFixedHeight(150)
        tb_w.setStyleSheet(
            f"background:{c['code']};color:{c['warn']};"
            f"border:1px solid {c['border']};border-radius:6px;"
            f"font-family:Consolas,monospace;font-size:10px;padding:6px;")
        lay.addWidget(tb_w)
        lay.addStretch()
        scroll.setWidget(body); root.addWidget(scroll, 1)

        # Button bar
        bb = QWidget(); bb.setFixedHeight(52)
        bb.setStyleSheet(f"background:{c['panel']};border-top:1px solid {c['border']};")
        bbl = QHBoxLayout(bb); bbl.setContentsMargins(20,0,20,0); bbl.setSpacing(8)
        copy_b  = self._btn("📋  Скопировать лог",  self._copy)
        close_b = self._btn("✕  Закрыть",           self.close, c['error'],   "white")
        retry_b = self._btn("🔄  Попробовать снова", self._retry,"#1E4A8A", "#5AA3FF")
        bbl.addWidget(copy_b); bbl.addStretch()
        bbl.addWidget(retry_b); bbl.addWidget(close_b)
        root.addWidget(bb)

    def _card(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background:{_C['card']};border:1px solid {_C['border']};border-radius:8px;")
        return w

    def _sect(self, t: str) -> QLabel:
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{_C['muted']};font-size:9px;font-weight:700;"
            f"letter-spacing:1.5px;background:transparent;")
        return l

    def _diag_card(self, d: dict) -> QWidget:
        c = _C
        sc = {"error": c['error'], "warning": c['warn']}.get(d["severity"], c['accent'])
        w  = self._card()
        w.setStyleSheet(
            f"background:{c['card']};border:1px solid {sc};"
            f"border-left:3px solid {sc};border-radius:8px;")
        cl = QVBoxLayout(w); cl.setContentsMargins(14,10,14,10); cl.setSpacing(5)
        icon = "🔴" if d["severity"]=="error" else "🟡"
        tl   = QLabel(f"{icon}  {d['title']}")
        tl.setStyleSheet(f"color:{sc};font-size:12px;font-weight:600;")
        cl.addWidget(tl)
        for i, fix in enumerate(d["fixes"]):
            row = QHBoxLayout(); row.setSpacing(6)
            nl  = QLabel(f"{i+1}.")
            nl.setFixedWidth(16)
            nl.setStyleSheet(f"color:{c['muted']};font-size:10px;")
            fl  = QLabel(fix); fl.setWordWrap(True)
            fl.setStyleSheet(
                f"color:{c['text']};font-size:11px;font-family:Consolas,monospace;")
            row.addWidget(nl, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(fl, 1)
            cl.addLayout(row)
        return w

    def _btn(self, text, slot, bg="#1F2433", fg="#8A92A8") -> QPushButton:
        b = QPushButton(text); b.setFixedHeight(32)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg};"
            f"border-radius:6px;font-size:11px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{fg};color:white;}}")
        b.clicked.connect(slot); return b

    def _copy(self):
        QApplication.clipboard().setText(self._tb)

    def _retry(self):
        self.close()
        try:
            import subprocess
            subprocess.Popen([sys.executable, "main.py"],
                             cwd=os.path.dirname(os.path.abspath(sys.argv[0])))
        except Exception: pass


def show_startup_error(error: Exception, tb_str: str = "") -> None:
    """Show error dialog. Safe to call before or after QApplication exists."""
    import traceback
    if not tb_str:
        tb_str = traceback.format_exc()

    app = QApplication.instance()
    created = False
    if app is None:
        app = QApplication(sys.argv)
        created = True

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,     QColor("#0F1117"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#E8ECF4"))
    app.setPalette(pal)

    dlg = StartupErrorDialog(error, tb_str)
    dlg.exec()
    if created:
        sys.exit(1)
