"""
MacroX — pynput cross-platform compatibility.
Mouse button names differ by OS and pynput version:
  Windows:  Button.x1, Button.x2
  Linux:    Button.button8, Button.button9
  macOS:    Button.button3, Button.button4 (varies)
"""
import logging
log = logging.getLogger(__name__)

def build_mouse_map() -> dict:
    """
    Returns {pynput.Button -> human_name} dict built dynamically
    so it works regardless of OS/pynput version.
    """
    try:
        from pynput.mouse import Button
    except ImportError:
        return {}

    result = {}

    # Standard buttons — always present
    for btn_name, human in [
        ("left",   "Mouse1"),
        ("right",  "Mouse2"),
        ("middle", "Mouse3"),
    ]:
        b = getattr(Button, btn_name, None)
        if b is not None:
            result[b] = human

    # Extra buttons — try all known names for Mouse4 / Mouse5
    MOUSE4_CANDIDATES = ["x1", "button8", "button4", "side"]
    MOUSE5_CANDIDATES = ["x2", "button9", "button5", "extra"]

    for human, candidates in [("Mouse4", MOUSE4_CANDIDATES),
                               ("Mouse5", MOUSE5_CANDIDATES)]:
        for name in candidates:
            b = getattr(Button, name, None)
            if b is not None:
                result[b] = human
                log.debug(f"Mapped {name} → {human}")
                break
        else:
            log.warning(f"Could not map {human}: tried {candidates}")

    log.info(f"pynput MOUSE_MAP built: {len(result)} entries: "
             f"{[f'{b.name}→{h}' for b,h in result.items()]}")
    return result
