"""
MacroX — Comprehensive logging system.
- trace_calls: logs every call/return/exception
- setup_logging: file + UI handlers, installed once at startup
- Session buffer: stores all messages so debug window shows history on reopen
"""
import sys, os, traceback, logging, datetime, functools, inspect
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal

LOG_DIR  = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "logs"
LOG_DIR.mkdir(exist_ok=True)
_session = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOG_DIR / f"macrox_{_session}.log"

# ── Signal bridge + in-memory session buffer ──────────────────────────────────
class _Bridge(QObject):
    new_entry = pyqtSignal(str, str)   # levelname, formatted_message

_bridge      = _Bridge()
_session_buf: list[tuple[str,str]] = []   # [(levelname, message), ...]
_MAX_BUF     = 10_000                      # keep last 10k entries in memory

def get_bridge() -> _Bridge:
    return _bridge

def get_session_buffer() -> list[tuple[str,str]]:
    """Returns all log entries captured since app start."""
    return list(_session_buf)

# ── Handlers ──────────────────────────────────────────────────────────────────
class _UIHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            # Store in session buffer
            _session_buf.append((record.levelname, msg))
            if len(_session_buf) > _MAX_BUF:
                del _session_buf[: _MAX_BUF // 10]   # trim oldest 10%
            # Emit to signal (debug window if open)
            _bridge.new_entry.emit(record.levelname, msg)
        except Exception:
            pass

class _SafeFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        try: self.flush()
        except Exception: pass

_FMT = logging.Formatter(
    "%(asctime)s.%(msecs)03d  %(levelname)-8s  %(name)s.%(funcName)s:%(lineno)d  —  %(message)s",
    datefmt="%H:%M:%S"
)

_ready = False

def setup_logging(level=logging.DEBUG):
    global _ready
    if _ready: return
    _ready = True

    root = logging.getLogger()
    root.setLevel(level)

    fh = _SafeFileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setFormatter(_FMT); fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    uh = _UIHandler()
    uh.setFormatter(_FMT); uh.setLevel(logging.DEBUG)
    root.addHandler(uh)

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb); return
        logging.critical(
            "UNHANDLED EXCEPTION:\n" +
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
    sys.excepthook = _hook
    logging.info(f"=== MacroX session started === log: {LOG_FILE}")


# ── trace_calls decorator ─────────────────────────────────────────────────────
def trace_calls(func):
    logger       = logging.getLogger(func.__module__)
    sig          = inspect.signature(func)
    _params      = list(sig.parameters.values())
    _max_posit   = sum(1 for p in _params
                       if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY))
    _has_var     = any(p.kind == p.VAR_POSITIONAL for p in _params)
    _param_names = [p.name for p in _params]

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Trim extra Qt signal args (e.g. clicked → False)
        if not _has_var and len(args) > _max_posit:
            trimmed = args[:_max_posit]
            extra   = args[_max_posit:]
            logger.debug(f"TRIM  {func.__qualname__}: dropped Qt extra args {extra}")
            args = trimmed

        arg_parts = []
        for i, a in enumerate(args):
            name = _param_names[i] if i < len(_param_names) else f"arg{i}"
            if name == "self": continue
            arg_parts.append(f"{name}={_safe_repr(a)}")
        for k, v in kwargs.items():
            arg_parts.append(f"{k}={_safe_repr(v)}")

        logger.debug(f"CALL  {func.__qualname__}({', '.join(arg_parts)})")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"RETN  {func.__qualname__} → {_safe_repr(result)}")
            return result
        except Exception as exc:
            logger.error(f"EXCP  {func.__qualname__} raised {type(exc).__name__}: {exc}")
            raise

    return wrapper


def _safe_repr(val, max_len=120) -> str:
    try:
        s = repr(val)
        return s[:max_len] + "..." if len(s) > max_len else s
    except Exception:
        return "<repr-error>"
