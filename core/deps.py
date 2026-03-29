"""
MacroX — Dependency auto-installer.
Runs before UI starts to ensure all packages exist in current Python.
"""
import sys, subprocess, importlib, logging
log = logging.getLogger(__name__)

REQUIRED = [
    ("PyQt6",    "PyQt6"),
    ("pynput",   "pynput"),
    ("cv2",      "opencv-python"),
    ("mss",      "mss"),
    ("numpy",    "numpy"),
    ("PIL",      "Pillow"),
]

def ensure_deps() -> list:
    missing = []
    for mod_name, pip_name in REQUIRED:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            log.warning(f"Package missing: {pip_name} — auto-installing...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name, "--quiet"],
                    timeout=120, stderr=subprocess.DEVNULL
                )
                importlib.import_module(mod_name)
                log.info(f"Auto-installed: {pip_name}")
            except Exception as e:
                log.error(f"Failed to install {pip_name}: {e}")
                missing.append(pip_name)
    return missing
