"""
MacroX — OCR Engine Manager

Handles detection, installation guidance, and text/number recognition
using Tesseract (via pytesseract) or EasyOCR.

Public API:
  get_ocr_engine()               → OcrEngine singleton
  OcrEngine.status()             → dict with availability info
  OcrEngine.read_number(img)     → int | None
  OcrEngine.read_text(img)       → str
  OcrEngine.test_image(img)      → dict {tesseract: str, easyocr: str, preferred: str}
"""
import logging, subprocess, sys, os, site
from pathlib import Path

def _ensure_user_site_on_path():
    """
    On Windows pip often installs to AppData/Roaming/Python/PythonXXX/site-packages
    which is not always in sys.path when the app is launched via a shortcut or IDE.
    This adds it so imports like easyocr / pytesseract work without admin rights.
    """
    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.insert(0, user_site)
    # Also add the Scripts dir sibling (for PATH-less CLI tools — not needed for import)
    # Some packages install data next to site-packages
    roaming_base = str(Path(user_site).parent.parent)  # …/Python/PythonXXX
    for subdir in ["site-packages", "Lib/site-packages"]:
        p = str(Path(roaming_base) / subdir)
        if Path(p).exists() and p not in sys.path:
            sys.path.insert(0, p)

_ensure_user_site_on_path()

log = logging.getLogger(__name__)

# ── Settings persistence ──────────────────────────────────────────────────────
def _load_ocr_settings() -> dict:
    try:
        from core.font_scale import _load_settings
        s = _load_settings()
        return {
            "preferred_engine": s.get("ocr_engine", "auto"),
            "tesseract_path":   s.get("tesseract_path", ""),
        }
    except Exception:
        return {"preferred_engine": "auto", "tesseract_path": ""}

def _save_ocr_settings(data: dict):
    try:
        from core.font_scale import _load_settings, _save_settings
        s = _load_settings()
        s.update(data)
        _save_settings(s)
    except Exception as e:
        log.error(f"save ocr settings: {e}")


# ── Engine probes ─────────────────────────────────────────────────────────────
def _probe_tesseract(custom_path: str = "") -> tuple[bool, str]:
    """Returns (available, version_or_error)."""
    import shutil
    try:
        import pytesseract
        # Apply custom path if given
        if custom_path:
            pytesseract.pytesseract.tesseract_cmd = custom_path
        elif sys.platform == "win32":
            # Common Windows install path
            default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if Path(default).exists():
                pytesseract.pytesseract.tesseract_cmd = default
        ver = pytesseract.get_tesseract_version()
        return True, f"Tesseract {ver}"
    except ImportError:
        return False, "pytesseract не установлен (pip install pytesseract)"
    except Exception as e:
        return False, f"Tesseract не найден: {e}"


def _probe_easyocr() -> tuple[bool, str]:
    """Returns (available, version_or_error)."""
    try:
        import easyocr
        ver = getattr(easyocr, "__version__", "?")
        return True, f"EasyOCR {ver}"
    except ImportError:
        return False, "easyocr не установлен (pip install easyocr)"
    except Exception as e:
        return False, f"EasyOCR ошибка: {e}"


def _probe_opencv() -> tuple[bool, str]:
    try:
        import cv2
        return True, f"OpenCV {cv2.__version__}"
    except ImportError:
        return False, "opencv-python не установлен"


# ── Image preprocessing ───────────────────────────────────────────────────────
def _preprocess_for_ocr(pil_img, scale: int = 4):
    """
    Upscale + contrast boost for small game UI numbers.
    Returns both PIL and numpy versions.
    """
    from PIL import Image, ImageFilter, ImageEnhance
    import numpy as np

    # Upscale
    w, h = pil_img.size
    big = pil_img.resize((w * scale, h * scale), Image.LANCZOS)

    # Greyscale + contrast
    grey = big.convert("L")
    enhanced = ImageEnhance.Contrast(grey).enhance(2.5)
    sharp    = enhanced.filter(ImageFilter.SHARPEN)

    # Threshold — white/yellow text on dark background
    arr = np.array(sharp)
    # Bright pixels = text
    binary = (arr > 140).astype("uint8") * 255
    from PIL import Image as PILImage
    result = PILImage.fromarray(binary)
    return result


# ── Tesseract reader ──────────────────────────────────────────────────────────
def _read_with_tesseract(pil_img, custom_path: str = "") -> str:
    import pytesseract
    if custom_path:
        pytesseract.pytesseract.tesseract_cmd = custom_path
    elif sys.platform == "win32":
        default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if Path(default).exists():
            pytesseract.pytesseract.tesseract_cmd = default

    preprocessed = _preprocess_for_ocr(pil_img)
    cfg = "--psm 7 -c tessedit_char_whitelist=0123456789"
    raw = pytesseract.image_to_string(preprocessed, config=cfg).strip()
    import re
    m = re.search(r"\d+", raw)
    return m.group() if m else ""


# ── EasyOCR reader ────────────────────────────────────────────────────────────
_easyocr_reader      = None
_easyocr_state       = "idle"
_easyocr_state_msg   = ""


# ── Qt signal bridge (thread-safe UI notifications) ───────────────────────────
# Lazily created so ocr_engine can be imported without Qt being fully up yet
_ocr_signals = None

def _get_ocr_signals():
    global _ocr_signals
    if _ocr_signals is None:
        try:
            from PyQt6.QtCore import QObject, pyqtSignal
            class _OcrSignals(QObject):
                state_changed = pyqtSignal(str, str)  # (state, msg)
            _ocr_signals = _OcrSignals()
        except Exception:
            _ocr_signals = None
    return _ocr_signals


def _set_easyocr_state(state: str, msg: str = ""):
    global _easyocr_state, _easyocr_state_msg
    _easyocr_state     = state
    _easyocr_state_msg = msg
    log.info(f"EasyOCR state: {state}  {msg}")
    sig = _get_ocr_signals()
    if sig is not None:
        try:
            sig.state_changed.emit(state, msg)
        except Exception as e:
            log.debug(f"OCR signal emit error: {e}")


def get_easyocr_state() -> tuple[str, str]:
    """Returns (state, message). state: idle/downloading/loading/ready/error."""
    return _easyocr_state, _easyocr_state_msg


def add_easyocr_state_listener(cb):
    """
    cb(state: str, msg: str) — connected via Qt signal, so it is always
    delivered on the main thread regardless of which thread sets the state.
    """
    sig = _get_ocr_signals()
    if sig is not None:
        try:
            sig.state_changed.connect(cb)
        except Exception as e:
            log.debug(f"add_easyocr_state_listener error: {e}")

def remove_easyocr_state_listener(cb):
    sig = _get_ocr_signals()
    if sig is not None:
        try:
            sig.state_changed.disconnect(cb)
        except Exception:
            pass


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader

    import easyocr, os
    from pathlib import Path

    # Check if models already downloaded
    model_dir  = Path.home() / ".EasyOCR" / "model"
    # EasyOCR needs craft_mlt_25k.pth and english_g2.pth (~90MB total)
    craft_ok   = (model_dir / "craft_mlt_25k.pth").exists()
    eng_ok     = (model_dir / "english_g2.pth").exists()
    need_dl    = not (craft_ok and eng_ok)

    if need_dl:
        _set_easyocr_state(
            "downloading",
            "Первый запуск: скачивание моделей (~90 МБ). "
            "Это займёт несколько минут. Дальнейшие запуски будут мгновенными.")
    else:
        _set_easyocr_state("loading", "Загрузка EasyOCR моделей в память...")

    try:
        _easyocr_reader = easyocr.Reader(["en"], verbose=False)
        _set_easyocr_state("ready", "EasyOCR готов к работе")
    except Exception as e:
        _set_easyocr_state("error", str(e))
        raise
    return _easyocr_reader


def warmup_easyocr_async():
    """
    Pre-load EasyOCR Reader in a background thread at app startup.
    After this, actual OCR calls have no cold-start delay (~30-80ms each).
    """
    import threading
    easy_ok, _ = _probe_easyocr()
    if not easy_ok:
        return
    if _easyocr_state in ("ready", "downloading", "loading"):
        return
    log.info("EasyOCR: starting background warmup")
    threading.Thread(target=_get_easyocr_reader, daemon=True).start()


def _read_with_easyocr(pil_img) -> str:
    import numpy as np
    reader = _get_easyocr_reader()
    preprocessed = _preprocess_for_ocr(pil_img)
    arr = np.array(preprocessed.convert("RGB"))
    results = reader.readtext(arr, detail=0, allowlist="0123456789")
    import re
    text = " ".join(str(r) for r in results).strip()
    m = re.search(r"\d+", text)
    return m.group() if m else ""


# ── Main engine class ─────────────────────────────────────────────────────────
class OcrEngine:
    def __init__(self):
        self._settings = _load_ocr_settings()
        self._tess_ok  = None
        self._easy_ok  = None
        self._cv_ok    = None

    def reload_settings(self):
        self._settings = _load_ocr_settings()

    # ── Status ────────────────────────────────────────────────────────────────
    def status(self) -> dict:
        """Full status of all OCR components."""
        cfg = self._settings
        tess_ok, tess_msg = _probe_tesseract(cfg.get("tesseract_path",""))
        easy_ok, easy_msg = _probe_easyocr()
        cv_ok,   cv_msg   = _probe_opencv()
        preferred = cfg.get("preferred_engine","auto")

        if preferred == "auto":
            if tess_ok: active = "tesseract"
            elif easy_ok: active = "easyocr"
            else: active = "none"
        else:
            active = preferred if (
                (preferred == "tesseract" and tess_ok) or
                (preferred == "easyocr"  and easy_ok)
            ) else "none"

        return {
            "tesseract_available": tess_ok,
            "tesseract_msg":       tess_msg,
            "easyocr_available":   easy_ok,
            "easyocr_msg":         easy_msg,
            "opencv_available":    cv_ok,
            "opencv_msg":          cv_msg,
            "preferred":           preferred,
            "active_engine":       active,
        }

    # ── Read number ───────────────────────────────────────────────────────────
    def read_number(self, pil_img) -> int | None:
        """Read a number from image. Returns int or None."""
        txt = self.read_text(pil_img)
        try:
            return int(txt) if txt else None
        except ValueError:
            import re
            m = re.search(r"\d+", txt)
            return int(m.group()) if m else None

    def read_text(self, pil_img) -> str:
        """Read text from image using preferred engine."""
        st = self.status()
        eng = st["active_engine"]
        cfg = self._settings
        try:
            if eng == "tesseract":
                return _read_with_tesseract(pil_img, cfg.get("tesseract_path",""))
            elif eng == "easyocr":
                return _read_with_easyocr(pil_img)
            else:
                return ""
        except Exception as e:
            log.error(f"OCR read error ({eng}): {e}")
            return ""

    # ── Test both engines on image ────────────────────────────────────────────
    def test_image(self, pil_img) -> dict:
        """
        Run both engines on the same image.
        Returns dict with results from each engine.
        """
        cfg = self._settings
        results = {
            "tesseract": None,
            "easyocr":   None,
            "preferred": cfg.get("preferred_engine","auto"),
            "errors":    {},
        }

        tess_ok, _ = _probe_tesseract(cfg.get("tesseract_path",""))
        easy_ok, _ = _probe_easyocr()

        if tess_ok:
            try:
                results["tesseract"] = _read_with_tesseract(
                    pil_img, cfg.get("tesseract_path",""))
            except Exception as e:
                results["errors"]["tesseract"] = str(e)
        else:
            results["errors"]["tesseract"] = "Не установлен"

        if easy_ok:
            try:
                results["easyocr"] = _read_with_easyocr(pil_img)
            except Exception as e:
                results["errors"]["easyocr"] = str(e)
        else:
            results["errors"]["easyocr"] = "Не установлен"

        return results

    # ── Install helpers ───────────────────────────────────────────────────────
    def install_pytesseract(self, callback=None):
        """pip install pytesseract in background thread."""
        self._run_pip(["pytesseract"], callback)

    def install_easyocr(self, callback=None):
        """pip install easyocr in background thread."""
        self._run_pip(["easyocr"], callback)

    def fix_easyocr_torch(self, callback=None):
        """
        Reinstall EasyOCR with stable torch versions.
        Steps: uninstall torch/torchvision/easyocr -> install torch==2.8.0 + torchvision==0.23.0 -> install easyocr
        callback(ok_or_None, accumulated_output_str) — called after each step.
        """
        import threading

        UNINSTALL = ["torch", "torchvision", "easyocr"]
        TORCH_PKG = "torch==2.8.0"
        TV_PKG    = "torchvision==0.23.0"

        def _run_cmd(args, label, log_lines):
            sep = "-" * 44
            log_lines.append("")
            log_lines.append(sep)
            log_lines.append(">> " + label)
            log_lines.append(sep)
            if callback:
                callback(None, "\n".join(log_lines))
            try:
                proc = subprocess.run(
                    [sys.executable, "-m"] + args,
                    capture_output=True, text=True, timeout=300)
                out = (proc.stdout + proc.stderr).strip()
                log_lines.append(out)
                if callback:
                    callback(None, "\n".join(log_lines))
                return proc.returncode == 0
            except Exception as exc:
                log_lines.append("ERROR: " + str(exc))
                if callback:
                    callback(None, "\n".join(log_lines))
                return False

        def _worker():
            log = []
            log.append("MacroX: исправление EasyOCR (совместимые версии torch)")
            _run_cmd(["pip", "uninstall", "-y"] + UNINSTALL,
                     "Шаг 1/3: удаление torch / torchvision / easyocr", log)
            ok2 = _run_cmd(["pip", "install", TORCH_PKG, TV_PKG],
                           "Шаг 2/3: установка torch==2.8.0 + torchvision==0.23.0", log)
            ok3 = _run_cmd(["pip", "install", "easyocr"],
                           "Шаг 3/3: установка easyocr", log)
            log.append("")
            if ok2 and ok3:
                log.append("OK  Готово. Нажмите 'Проверить' для обновления статуса.")
            else:
                log.append("ERR Ошибка на одном из шагов — см. вывод выше.")
            if callback:
                callback(ok2 and ok3, "\n".join(log))

        threading.Thread(target=_worker, daemon=True).start()

    def _run_pip(self, packages: list, callback=None):
        import threading
        def _worker():
            try:
                cmd = [sys.executable, "-m", "pip", "install",
                       "--break-system-packages"] + packages
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180)
                ok  = proc.returncode == 0
                out = proc.stdout + proc.stderr
                if callback:
                    callback(ok, out)
            except Exception as e:
                if callback:
                    callback(False, str(e))
        threading.Thread(target=_worker, daemon=True).start()

    def set_preferred(self, engine: str):
        """engine: 'auto' | 'tesseract' | 'easyocr'"""
        self._settings["preferred_engine"] = engine
        _save_ocr_settings({"ocr_engine": engine})

    def set_tesseract_path(self, path: str):
        self._settings["tesseract_path"] = path
        _save_ocr_settings({"tesseract_path": path})


# ── Singleton ─────────────────────────────────────────────────────────────────
_ocr_engine: OcrEngine | None = None

def get_ocr_engine() -> OcrEngine:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = OcrEngine()
    return _ocr_engine
