"""
MacroX — Font Scale Manager

Two independent scales:
  global_scale  → affects the whole app (FONTS dict + stylesheet rebuild)
  journal_scale → affects only the Journal page (overrides global for journal)

Priority: journal_scale takes precedence inside LogPage.
Both persist to config/settings.json.
"""
import json, os, logging
from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

LEVELS = [
    {"name": "XS",  "mult": 0.82},
    {"name": "S",   "mult": 1.0},    # default
    {"name": "M",   "mult": 1.18},
    {"name": "L",   "mult": 1.38},
    {"name": "XL",  "mult": 1.6},
]

_BASE = {
    "xs": 10, "sm": 11, "md": 13, "lg": 15,
    "xl": 18, "xxl": 24,
}

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "settings.json"
)


def _load_settings() -> dict:
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"settings load: {e}")
    return {}


def _save_settings(data: dict):
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        existing = _load_settings()
        existing.update(data)
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        log.warning(f"settings save: {e}")


# ── Global font scale ─────────────────────────────────────────────────────────
class GlobalFontScale(QObject):
    """
    Controls app-wide font size.
    Writes to FONTS dict → triggers app stylesheet rebuild.
    """
    scale_changed = pyqtSignal(int)   # level index

    def __init__(self):
        super().__init__()
        self._level = 1
        d = _load_settings()
        self._level = max(0, min(len(LEVELS)-1, d.get("global_font_level", 1)))
        self._apply()

    def level(self) -> int:     return self._level
    def mult(self) -> float:    return LEVELS[self._level]["mult"]
    def label(self) -> str:     return LEVELS[self._level]["name"]

    def set_level(self, level: int):
        level = max(0, min(len(LEVELS)-1, level))
        if level == self._level: return
        self._level = level
        self._apply()
        _save_settings({"global_font_level": level})
        self.scale_changed.emit(level)
        log.info(f"Global font → {LEVELS[level]['name']} ×{LEVELS[level]['mult']}")

    def px(self, key: str) -> str:
        return f"{max(8, round(_BASE.get(key,13) * self.mult()))}px"

    def pt(self, key: str) -> int:
        return max(8, round(_BASE.get(key,13) * self.mult()))

    def _apply(self):
        from ui.theme import FONTS
        m = self.mult()

        # 1. Update FONTS dict — all stylesheet builders read from here
        for k, b in _BASE.items():
            FONTS[f"size_{k}"] = f"{max(8, round(b * m))}px"

        # 2. Set QApplication default font so ALL widgets inherit the new
        #    size automatically — even those built before scale change
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QFont
            app = QApplication.instance()
            if app:
                base_pt = max(8, round(13 * m))
                app.setFont(QFont("Segoe UI", base_pt))
        except Exception:
            pass  # Qt not ready yet (called during module import)

    def size(self, key: str) -> int:
        """
        Scaled UI element size for compact/expanded layouts.
        Use for button heights, row heights, paddings — not font sizes.
        Scales proportionally with font so layout stays balanced.

        Keys: btn_h, row_h, topbar_h, sidebar_w, input_h, pad_sm, pad_md, pad_lg
        """
        _SIZES = {
            "btn_h":     28, "btn_h_lg": 36,  "row_h":    46,
            "topbar_h":  60, "sidebar_w": 210, "input_h":  30,
            "pad_sm":     4, "pad_md":     8,  "pad_lg":   16,
            "icon_sz":   44, "status_h":  52,
        }
        base = _SIZES.get(key, 28)
        return max(4, round(base * self.mult()))


# ── Journal-local font scale ──────────────────────────────────────────────────
class JournalFontScale(QObject):
    """
    Controls font size ONLY inside the Journal page.
    Has higher priority than global scale for journal content.
    Operates as a multiplier on top of the BASE sizes (not on global).
    """
    scale_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._level = 1   # default = S (1.0x, same as global baseline)
        d = _load_settings()
        self._level = max(0, min(len(LEVELS)-1, d.get("journal_font_level", 1)))

    def level(self) -> int:     return self._level
    def mult(self) -> float:    return LEVELS[self._level]["mult"]
    def label(self) -> str:     return LEVELS[self._level]["name"]

    def set_level(self, level: int):
        level = max(0, min(len(LEVELS)-1, level))
        if level == self._level: return
        self._level = level
        _save_settings({"journal_font_level": level})
        self.scale_changed.emit(level)
        log.info(f"Journal font → {LEVELS[level]['name']} ×{LEVELS[level]['mult']}")

    def px(self, key: str) -> str:
        """Returns pixel size string using BASE sizes scaled by journal mult."""
        return f"{max(8, round(_BASE.get(key,13) * self.mult()))}px"

    def pt(self, key: str) -> int:
        return max(8, round(_BASE.get(key,13) * self.mult()))


# ── Singletons ────────────────────────────────────────────────────────────────
_global:  GlobalFontScale  | None = None
_journal: JournalFontScale | None = None


def get_global_font() -> GlobalFontScale:
    global _global
    if _global is None:
        _global = GlobalFontScale()
    return _global


def get_journal_font() -> JournalFontScale:
    global _journal
    if _journal is None:
        _journal = JournalFontScale()
    return _journal


# Keep backward compat: existing code that calls get_font_scale() gets global
def get_font_scale() -> GlobalFontScale:
    return get_global_font()


# ── Time formatter ────────────────────────────────────────────────────────────
def fmt_duration(ms: int) -> str:
    """
    Format milliseconds into readable string — no ms precision for user display.
      < 1 000        → "< 1с"
      < 60 000       → "42с"
      < 3 600 000    → "12м 34с"
      ≥ 3 600 000    → "2ч 15м 34с"
    """
    if ms <= 0:      return "—"
    if ms < 1_000:   return "< 1с"
    s = ms // 1000
    if s < 60:       return f"{s}с"
    if s < 3600:     return f"{s//60}м {s%60:02d}с"
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}ч {m:02d}м {sec:02d}с"
