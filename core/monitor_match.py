"""
MacroX — Template Matching & OCR engine

Provides two zone types on top of pixel-similarity:

  TYPE "template" — template matching (for shifting buffs)
    search_rect  : [x,y,w,h]  — wide area to search inside (full buff bar)
    template     : b64 PNG    — small icon to find
    match_thresh : 0.0-1.0    — confidence threshold (default 0.75)
    condition    : "found" | "not_found"
    match_mode   : "icon_only" | "icon_value_lt" | "icon_value_gt" | "icon_value_eq"
    value_target : int        — for numeric comparisons
    value_region : "below"|"above"|"right"|"left"|"overlay" (where number appears)

  TYPE "pixel" — classic pixel similarity (existing behaviour)

OCR is attempted with pytesseract if available, with numpy digit-area fallback.
"""
import base64, logging, time
from io import BytesIO
import numpy as np

log = logging.getLogger(__name__)


# ── Image helpers ─────────────────────────────────────────────────────────────
def _pil_to_cv(img):
    import cv2
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _b64_to_pil(b64: str):
    from PIL import Image
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")


def _apply_circle_mask(img_pil, shape_meta: dict):
    """
    If zone has shape='circle', zero-out pixels outside the circle
    before comparison. shape_meta: {cx_rel, cy_rel, r_rel} (relative to rect).
    """
    import numpy as np
    arr = np.array(img_pil.convert("RGBA"), dtype=np.uint8)
    h, w = arr.shape[:2]
    cx = shape_meta.get("cx_rel", w//2)
    cy = shape_meta.get("cy_rel", h//2)
    r  = shape_meta.get("r_rel",  min(w,h)//2)
    Y, X = np.ogrid[:h, :w]
    mask = (X - cx)**2 + (Y - cy)**2 > r**2
    arr[mask] = 0
    from PIL import Image
    return Image.fromarray(arr).convert("RGB")


# ── Similarity (pixel mode) ───────────────────────────────────────────────────
def pixel_similarity(img_a, img_b, shape_meta: dict | None = None) -> float:
    """Fraction of pixels with all-channel diff < 30."""
    a = np.array(img_a.convert("RGB"), dtype=np.int16)
    b = np.array(img_b.convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        from PIL import Image
        b = np.array(
            img_b.resize((img_a.width, img_a.height)).convert("RGB"),
            dtype=np.int16)

    if shape_meta and shape_meta.get("shape") == "circle":
        # Only count pixels inside the circle mask
        h, w = a.shape[:2]
        cx = shape_meta.get("cx_rel", w//2)
        cy = shape_meta.get("cy_rel", h//2)
        r  = shape_meta.get("r_rel",  min(w,h)//2)
        Y, X = np.ogrid[:h, :w]
        inside = (X - cx)**2 + (Y - cy)**2 <= r**2
        if inside.sum() == 0:
            return 0.0
        diff  = np.abs(a - b)
        match = (diff < 30).all(axis=2)
        return float(match[inside].mean())

    diff  = np.abs(a - b)
    match = (diff < 30).all(axis=2)
    return float(match.mean())


# ── Template matching ─────────────────────────────────────────────────────────
def template_match(search_img, template_img,
                   thresh: float = 0.75) -> tuple[bool, float, tuple | None]:
    """
    Find template_img inside search_img using cv2.matchTemplate.
    Returns (found: bool, best_score: float, location: (x,y) | None)
    Falls back to sliding-window numpy if cv2 unavailable.
    """
    try:
        import cv2
        src  = _pil_to_cv(search_img)
        tpl  = _pil_to_cv(template_img)
        if tpl.shape[0] > src.shape[0] or tpl.shape[1] > src.shape[1]:
            return False, 0.0, None
        result = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        found = float(max_val) >= thresh
        return found, float(max_val), max_loc if found else None

    except ImportError:
        return _numpy_template_match(search_img, template_img, thresh)


def _numpy_template_match(search_img, template_img,
                           thresh: float) -> tuple[bool, float, tuple | None]:
    """Pure numpy fallback — slower but no cv2 dependency."""
    src = np.array(search_img.convert("RGB"), dtype=np.float32)
    tpl = np.array(template_img.convert("RGB"), dtype=np.float32)
    sh, sw = src.shape[:2]
    th, tw = tpl.shape[:2]
    if th > sh or tw > sw:
        return False, 0.0, None

    best_score = 0.0; best_loc = None
    # Stride = 2 for speed
    for y in range(0, sh - th + 1, 2):
        for x in range(0, sw - tw + 1, 2):
            patch = src[y:y+th, x:x+tw]
            diff  = np.abs(patch - tpl).mean() / 255.0
            score = 1.0 - diff
            if score > best_score:
                best_score = score; best_loc = (x, y)

    found = best_score >= thresh
    return found, best_score, best_loc if found else None


# ── OCR for number on/near icon ───────────────────────────────────────────────
def read_number_near_icon(search_img, loc: tuple,
                          template_size: tuple,
                          value_region: str = "below") -> int | None:
    """
    Crop the number area near the found icon and read it.
    loc          : (x, y) top-left of matched icon in search_img
    template_size: (w, h)
    value_region : "below"|"above"|"right"|"left"|"overlay"
    """
    from PIL import Image
    ix, iy   = loc
    tw, th   = template_size
    pad      = 4

    if value_region == "below":
        crop_box = (ix, iy+th-pad, ix+tw, iy+th+th//2)
    elif value_region == "above":
        crop_box = (ix, iy-th//2, ix+tw, iy+pad)
    elif value_region == "right":
        crop_box = (ix+tw, iy, ix+tw+tw, iy+th)
    elif value_region == "left":
        crop_box = (max(0,ix-tw), iy, ix, iy+th)
    else:  # overlay
        crop_box = (ix, iy, ix+tw, iy+th)

    sw, sh = search_img.size
    crop_box = (
        max(0, crop_box[0]), max(0, crop_box[1]),
        min(sw, crop_box[2]), min(sh, crop_box[3])
    )
    if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
        return None

    num_img = search_img.crop(crop_box)
    return _ocr_number(num_img)


def _ocr_number(img) -> int | None:
    """Try pytesseract, fallback to white-pixel digit heuristic."""
    # 1. Upscale for better OCR
    from PIL import Image
    scale = max(1, 48 // max(img.height, 1))
    big   = img.resize(
        (img.width * scale, img.height * scale),
        Image.NEAREST
    )

    # 2. Try tesseract
    try:
        import pytesseract
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789:"
        txt = pytesseract.image_to_string(big, config=cfg).strip()
        # Extract first integer
        import re
        m = re.search(r"\d+", txt)
        if m: return int(m.group())
    except Exception:
        pass

    # 3. Numpy fallback — count bright pixels per column (rough digit count)
    arr = np.array(big.convert("L"))
    bright = (arr > 180).astype(np.uint8)
    # Vertical projection — find non-empty columns → rough digit width
    proj = bright.sum(axis=0)
    non_zero = np.where(proj > 0)[0]
    if len(non_zero) == 0:
        return None
    # Heuristic: width ÷ ~6px per digit
    digit_width = max(1, (non_zero[-1] - non_zero[0]) // scale)
    return digit_width if digit_width > 0 else None


# ── Zone evaluator ─────────────────────────────────────────────────────────────
class ZoneEvaluator:
    """
    Evaluates a single zone based on its type ('pixel' or 'template').
    Returns (state: str, score: float)
      state: "match" | "no_match" | "error"
    """
    def __init__(self, zone: dict):
        self.zone      = zone
        self._ref      = None
        self._template = None
        self._load_images()

    def _load_images(self):
        z = self.zone
        ztype = z.get("zone_type", "pixel")
        if ztype == "template":
            b64 = z.get("template", "")
            if b64: self._template = _b64_to_pil(b64)
        else:
            b64 = z.get("reference", "")
            if b64: self._ref = _b64_to_pil(b64)

    def update(self, zone: dict):
        old_ref = self.zone.get("reference","") + self.zone.get("template","")
        self.zone = zone
        new_ref = zone.get("reference","") + zone.get("template","")
        if old_ref != new_ref: self._load_images()

    def evaluate(self, capture_fn) -> tuple[str, float]:
        z = self.zone
        ztype = z.get("zone_type", "pixel")

        if ztype == "ocr_read":
            raise RuntimeError("Use eval_ocr_read() directly for ocr_read zones")
        if ztype == "template":
            return self._eval_template(capture_fn)
        else:
            return self._eval_pixel(capture_fn)

    def eval_ocr_read(self, capture_fn) -> tuple[object, str]:
        """
        For ocr_read zones: capture fixed region, run OCR, return (value_or_None, display_str).
        Does NOT go through trigger/pipeline — called directly from engine polling loop.
        """
        import re
        rect = self.zone.get("rect", [0, 0, 64, 64])
        img  = capture_fn(rect)
        if img is None:
            return None, "capture_fail"
        try:
            from core.ocr_engine import get_ocr_engine
            raw = get_ocr_engine().read_text(img)
        except Exception as e:
            log.debug(f"eval_ocr_read OCR error: {e}")
            return None, "ocr_err"
        ocr_mode = self.zone.get("ocr_mode", "int")
        if not raw:
            return None, "—"
        if ocr_mode == "int":
            m = re.search(r"\d+", raw)
            return (int(m.group()), m.group()) if m else (None, f"?({raw[:8]})")
        else:
            cleaned = raw.strip()
            return (cleaned or None, cleaned or "—")

    def _eval_pixel(self, capture_fn) -> tuple[str, float]:
        if not self._ref: return "error", 0.0
        cur = capture_fn(self.zone.get("rect", [0,0,64,64]))
        if cur is None: return "error", 0.0
        shape_meta = self._shape_meta()
        sim   = pixel_similarity(self._ref, cur, shape_meta)
        state = "match" if sim >= self.zone.get("threshold", 0.90) else "no_match"
        return state, sim

    def _eval_template(self, capture_fn) -> tuple[str, float]:
        if not self._template: return "error", 0.0
        sr = list(self.zone.get("search_rect", [0,0,200,60]))
        # Extend height downward to capture numbers below icons (e.g. "105" under buff)
        extend = self.zone.get("extend_below_px", 0)
        if extend > 0:
            sr = [sr[0], sr[1], sr[2], sr[3] + extend]
        search = capture_fn(sr)
        if search is None: return "error", 0.0

        thresh    = self.zone.get("match_thresh", 0.75)
        condition = self.zone.get("condition", "found")
        match_mode = self.zone.get("match_mode", "icon_only")

        # ── Grid mode: only check discrete cell positions ─────────────────────
        # Avoids matching against animated/changing background between icons.
        # zone.grid = {cell_w, cell_h, offset_x, offset_y, gap_x, gap_y}
        grid = self.zone.get("grid")
        if grid:
            found, score, loc = self._grid_match(search, grid, thresh)
        else:
            found, score, loc = template_match(search, self._template, thresh)

        # ── Numeric check ─────────────────────────────────────────────────────
        ocr_num = None
        if found and match_mode != "icon_only" and loc is not None:
            ocr_num = self._read_value_at(search, loc)
            if ocr_num is not None:
                target = self.zone.get("value_target", 0)
                if not self._check_value(ocr_num, match_mode, target):
                    found = False

        state = "match" if (
            (condition == "found"     and found) or
            (condition == "not_found" and not found)
        ) else "no_match"

        # ── Debug mode: save annotated screenshot ─────────────────────────────
        if self.zone.get("debug_capture", False):
            self._save_debug_image(search, loc, score, ocr_num, state)

        return state, score

    def _save_debug_image(self, search_img, loc, score, ocr_num, state):
        """Save annotated capture + template thumbnail to debug_captures/."""
        import time, os
        try:
            from PIL import ImageDraw, Image as PILImage
            out_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "debug_captures")
            os.makedirs(out_dir, exist_ok=True)

            tw, th = (self._template.size if self._template else (32, 32))

            # Build composite: [search image with annotations] [template] side by side
            sw, sh = search_img.size
            thumb_w = max(tw, 80); thumb_h = max(th + 20, 60)
            total_w = sw + thumb_w + 4
            total_h = max(sh, thumb_h)
            composite = PILImage.new("RGB", (total_w, total_h), (20, 20, 30))
            composite.paste(search_img.convert("RGB"), (0, 0))

            # Paste template thumbnail on the right
            if self._template:
                composite.paste(self._template.convert("RGB"), (sw + 2, 2))

            draw = ImageDraw.Draw(composite)
            draw.text((sw + 2, th + 4), "ЭТАЛОН", fill=(180, 180, 100))
            draw.text((sw + 2, th + 14), f"{tw}x{th}px", fill=(120, 120, 100))

            # Blue grid cells on the search part
            grid = self.zone.get("grid")
            if grid:
                cw = grid.get("cell_w", tw); ch = grid.get("cell_h", th)
                gx = grid.get("gap_x", 0);  gy = grid.get("gap_y", 0)
                ox = grid.get("offset_x", 0); oy = grid.get("offset_y", 0)
                x = ox
                while x + cw <= sw:
                    y = oy
                    while y + ch <= sh:
                        draw.rectangle([x, y, x+cw, y+ch],
                                       outline=(80, 120, 255), width=1)
                        y += ch + gy if (ch+gy) > 0 else ch + 1
                        if (ch+gy) <= 0: break
                    x += cw + gx if (cw+gx) > 0 else cw + 1
                    if (cw+gx) <= 0: break

            # Green/red match box
            if loc:
                x, y = loc
                col = (50, 220, 80) if state == "match" else (220, 60, 60)
                draw.rectangle([x, y, x+tw, y+th], outline=col, width=2)
                # Yellow OCR area
                ext = self.zone.get("extend_below_px", 0)
                ocr_h = max(ext, th // 2 + 8)
                draw.rectangle([x, y+th, x+tw, y+th+ocr_h],
                               outline=(255, 200, 0), width=1)
                draw.text((x+2, y+th+2), "OCR", fill=(255, 200, 0))
            else:
                # No match found — highlight where we searched
                draw.text((2, sh - 14), "НЕТ СОВПАДЕНИЙ — проверьте эталон и порог",
                          fill=(255, 80, 80))

            # Header label
            thresh = self.zone.get("match_thresh", 0.75)
            label  = f"score={score:.3f} state={state} ocr={ocr_num} thresh={thresh}"
            draw.rectangle([0, 0, total_w, 14], fill=(0, 0, 0))
            draw.text((2, 2), label, fill=(255, 255, 100))

            ts   = time.strftime("%H%M%S")
            name = self.zone.get("name", "zone").replace(" ", "_")
            path = os.path.join(out_dir, f"{ts}_{name}_{state}.png")
            composite.save(path)
            log.info(f"Debug capture → {path}")
        except Exception as e:
            log.debug(f"Debug save failed: {e}")

    def _grid_match(self, search_img, grid: dict,
                    thresh: float) -> tuple[bool, float, tuple | None]:
        """
        Grid-aware template matching.

        Strategy:
          1. For each grid cell position, run cv2.matchTemplate of the ORIGINAL
             template (not resized) INSIDE the cell crop.
             This finds the icon even if it doesn't fill the entire cell perfectly.
          2. Also run a full-image matchTemplate (no grid) as fallback —
             catches cases where the buff bar has scrolled/shifted and the icon
             is between grid positions.
          3. Return the best result from both strategies.

        This solves two problems visible in debug screenshots:
          - score=0.48 from resize artifacts (template resized to cell → blurry match)
          - shifted buff bar causing icon to fall between grid cells
        """
        tw, th  = self._template.size
        sw, sh  = search_img.size

        cell_w  = grid.get("cell_w",  tw)
        cell_h  = grid.get("cell_h",  th)
        off_x   = grid.get("offset_x", 0)
        off_y   = grid.get("offset_y", 0)
        gap_x   = grid.get("gap_x",   0)
        gap_y   = grid.get("gap_y",   0)
        step_x  = cell_w + gap_x
        step_y  = cell_h + gap_y

        best_score = 0.0
        best_loc   = None

        # ── Strategy 1: check each grid cell ──────────────────────────────────
        x = off_x
        while x + cell_w <= sw:
            y = off_y
            while y + cell_h <= sh:
                # Crop cell — slightly expanded by 4px to handle minor misalignment
                pad = 4
                cx0 = max(0, x - pad); cy0 = max(0, y - pad)
                cx1 = min(sw, x + cell_w + pad)
                cy1 = min(sh, y + cell_h + pad)
                cell = search_img.crop((cx0, cy0, cx1, cy1))

                if cell.width >= tw and cell.height >= th:
                    found_c, score_c, loc_c = template_match(cell, self._template, thresh)
                    if score_c > best_score:
                        best_score = score_c
                        # Translate loc back to search_img coordinates
                        if loc_c:
                            best_loc = (cx0 + loc_c[0], cy0 + loc_c[1])
                        else:
                            best_loc = (x, y)

                y += step_y if step_y > 0 else cell_h + 1
                if step_y <= 0: break
            x += step_x if step_x > 0 else cell_w + 1
            if step_x <= 0: break

        # ── Strategy 2: full-image fallback (handles shifted buff bar) ────────
        # Run on the whole search image — finds icon anywhere, ignores background
        if sw >= tw and sh >= th:
            found_f, score_f, loc_f = template_match(search_img, self._template, thresh)
            if score_f > best_score:
                best_score = score_f
                best_loc   = loc_f

        found = best_score >= thresh
        return found, best_score, best_loc if found else None

    def _read_value_at(self, search_img, loc: tuple) -> "int | None":
        """OCR the number near the found icon location.
        Respects ocr_off_x, ocr_off_y, ocr_shrink from zone settings."""
        import re
        tw, th    = self._template.size
        val_reg   = self.zone.get("value_region", "below")
        extend    = self.zone.get("extend_below_px", 0)
        ocr_ox    = self.zone.get("ocr_off_x",  0)
        ocr_oy    = self.zone.get("ocr_off_y",  0)
        ocr_sk    = max(0, self.zone.get("ocr_shrink", 0))
        x, y      = loc
        sw, sh    = search_img.size

        pad = 4
        if val_reg == "below":
            extra  = max(extend, th // 2 + 8)
            # Apply vertical offset and shrink
            x1 = x + ocr_sk + ocr_ox
            x2 = x + tw - ocr_sk + ocr_ox
            y1 = y + th - pad + ocr_oy
            y2 = y + th + extra + ocr_oy
            box = (x1, y1, x2, y2)
        elif val_reg == "above":
            x1 = x + ocr_sk + ocr_ox
            x2 = x + tw - ocr_sk + ocr_ox
            y1 = max(0, y - th // 2 + ocr_oy)
            y2 = y + pad + ocr_oy
            box = (x1, y1, x2, y2)
        elif val_reg == "right":
            box = (x + tw + ocr_ox, y + ocr_sk + ocr_oy,
                   x + tw * 2 + ocr_ox, y + th - ocr_sk + ocr_oy)
        elif val_reg == "left":
            box = (max(0, x - tw + ocr_ox), y + ocr_sk + ocr_oy,
                   x + ocr_ox, y + th - ocr_sk + ocr_oy)
        else:  # overlay
            box = (x + ocr_sk + ocr_ox, y + ocr_sk + ocr_oy,
                   x + tw - ocr_sk + ocr_ox, y + th - ocr_sk + ocr_oy)

        box = (max(0,box[0]), max(0,box[1]),
               min(sw,box[2]), min(sh,box[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None

        from core.ocr_engine import get_ocr_engine
        num_text = get_ocr_engine().read_text(search_img.crop(box))
        m = re.search(r"\d+", num_text)
        return int(m.group()) if m else None

    def _check_value(self, num: int, mode: str, target: int) -> bool:
        if mode == "icon_value_lt":  return num < target
        if mode == "icon_value_gt":  return num > target
        if mode == "icon_value_eq":  return num == target
        return True

    def _shape_meta(self) -> dict | None:
        z = self.zone
        if z.get("shape") != "circle": return None
        rect = z.get("rect", [0,0,64,64])
        w, h = rect[2], rect[3]
        return {
            "shape":  "circle",
            "cx_rel": z.get("cx_rel", w//2),
            "cy_rel": z.get("cy_rel", h//2),
            "r_rel":  z.get("r_rel",  min(w,h)//2),
        }
