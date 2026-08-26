"""Computer-vision UI element detection for CEF/opaque apps.

Find and click buttons, inputs, and links without UIA or accessibility APIs,
using edge detection + contour analysis on screenshots.

Ideal for CEF-rendered apps (NVIDIA App, Spotify, Discord, Steam, VS Code,
Teams, Slack) where UIA and CDP both fail to expose sub-elements.

Endpoints:
  POST /vision/detect  — find all clickable-looking elements in a screenshot
  POST /vision/click   — find and click a button by visual description
  POST /vision/ocr     — OCR a screen region using Windows built-in OCR
"""

import base64
import logging
import time
from io import BytesIO

from flask import jsonify, request
from shared import _json_body, _log, _missing_field

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency flags
# ---------------------------------------------------------------------------

_HAS_PIL = False
_HAS_NUMPY = False

try:
    from PIL import Image, ImageFilter
    _HAS_PIL = True
except ImportError:
    pass

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    pass

# Reuse Windows OCR from routes_ocr (avoids duplicating the WinRT / PowerShell logic)
_win_ocr_fn = None
try:
    from routes_ocr import _windows_ocr as _win_ocr_fn
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------

def _grab_region(region=None, window=None):
    """Capture the screen or a sub-region.  Returns (PIL.Image, (off_x, off_y))."""
    if not _HAS_PIL:
        return None, (0, 0)

    win_bbox = None
    if window:
        try:
            import pygetwindow as gw
            wins = [w for w in gw.getWindowsWithTitle(window) if w.title]
            if wins:
                w0 = wins[0]
                win_bbox = (int(w0.left), int(w0.top), int(w0.right), int(w0.bottom))
        except Exception:
            pass

    if region:
        rx = int(region.get("x", 0))
        ry = int(region.get("y", 0))
        rw = int(region.get("w", 0) or region.get("width", 0))
        rh = int(region.get("h", 0) or region.get("height", 0))
        if win_bbox:
            rx += win_bbox[0]
            ry += win_bbox[1]
        bbox = (rx, ry, rx + rw, ry + rh) if (rw > 0 and rh > 0) else None
    elif win_bbox:
        bbox = win_bbox
    else:
        bbox = None

    off_x = bbox[0] if bbox else 0
    off_y = bbox[1] if bbox else 0

    # Fast path: MSS (DXGI)
    try:
        import mss
        with mss.mss() as sct:
            if bbox:
                mon = {"left": bbox[0], "top": bbox[1],
                       "width": max(1, bbox[2] - bbox[0]),
                       "height": max(1, bbox[3] - bbox[1])}
                cap_off = (off_x, off_y)
            else:
                mon = sct.monitors[1]
                cap_off = (mon["left"], mon["top"])
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            return img, cap_off
    except Exception:
        pass

    # PIL fallback
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=bbox)
        return img, (off_x, off_y)
    except Exception as e:
        _log(f"[vision] capture failed: {e}")
        return None, (0, 0)


def _pil_to_png_b64(pil_img):
    buf = BytesIO()
    pil_img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Edge detection + dilation (pure PIL + numpy, no OpenCV)
# ---------------------------------------------------------------------------

def _edge_binary(pil_img):
    """Return grayscale PIL image where edge pixels are bright (0-255)."""
    gray = pil_img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # Threshold: keep only strong edges
    return edges.point(lambda p: 255 if p > 20 else 0, "L")


def _dilate_pil(binary_img, radius=8):
    """Morphological dilation via repeated MaxFilter passes.

    Each MaxFilter(size=9) expands edges by 4 pixels.  Two passes ≈ 8 px total,
    which is enough to bridge the gap between opposite sides of a button border.
    """
    result = binary_img
    passes = max(1, radius // 4)
    for _ in range(passes):
        result = result.filter(ImageFilter.MaxFilter(size=9))
    return result


# ---------------------------------------------------------------------------
# Connected-component blob finder (numpy path)
# ---------------------------------------------------------------------------

def _find_blobs_numpy(binary_arr, subsample=4, max_blobs=150):
    """Vectorized connected-component bounding boxes on a binary numpy array.

    Uses cv2.connectedComponentsWithStats or scipy.ndimage.label (both C
    implementations) for ~100x speedup over pure-Python DFS.  Falls back to a
    stack-based DFS only if neither library is installed.  Subsampling keeps
    label counts manageable: a 1920x1080 image becomes 480x270 before labeling.
    """
    sub = binary_arr[::subsample, ::subsample]
    mask = (sub > 0).astype(np.uint8)

    # Fast path 1: OpenCV connectedComponentsWithStats returns bounding boxes
    # directly in the stats array (LEFT, TOP, WIDTH, HEIGHT, AREA).
    try:
        import cv2
        n_labels, _labels, stats, _cent = cv2.connectedComponentsWithStats(
            mask, connectivity=4)
        blobs = []
        # Label 0 is background; skip it.
        for lbl in range(1, n_labels):
            sx = int(stats[lbl, cv2.CC_STAT_LEFT])
            sy = int(stats[lbl, cv2.CC_STAT_TOP])
            sw_ = int(stats[lbl, cv2.CC_STAT_WIDTH])
            sh_ = int(stats[lbl, cv2.CC_STAT_HEIGHT])
            bw = sw_ * subsample
            bh = sh_ * subsample
            if bw >= 15 and bh >= 8:
                blobs.append({"x": sx * subsample, "y": sy * subsample,
                              "w": bw, "h": bh})
                if len(blobs) >= max_blobs:
                    break
        return blobs
    except Exception:
        pass

    # Fast path 2: scipy.ndimage.label + find_objects (also C-implemented).
    try:
        from scipy import ndimage
        labels, num_features = ndimage.label(mask)
        if num_features <= 0:
            return []
        slices = ndimage.find_objects(labels)
        blobs = []
        for slc in slices:
            if slc is None:
                continue
            ys_slc, xs_slc = slc
            sw_ = xs_slc.stop - xs_slc.start
            sh_ = ys_slc.stop - ys_slc.start
            bw = sw_ * subsample
            bh = sh_ * subsample
            if bw >= 15 and bh >= 8:
                blobs.append({"x": int(xs_slc.start) * subsample,
                              "y": int(ys_slc.start) * subsample,
                              "w": bw, "h": bh})
                if len(blobs) >= max_blobs:
                    break
        return blobs
    except Exception:
        pass

    # Fallback: original pure-Python DFS (kept for environments without cv2/scipy).
    sh, sw = sub.shape
    visited = np.zeros((sh, sw), dtype=bool)
    blobs = []
    ys, xs = np.where(sub > 0)

    for idx in range(len(ys)):
        y0, x0 = int(ys[idx]), int(xs[idx])
        if visited[y0, x0]:
            continue

        stack = [(y0, x0)]
        visited[y0, x0] = True
        min_y = max_y = y0
        min_x = max_x = x0
        count = 0

        while stack and count < 5000:
            cy, cx = stack.pop()
            count += 1
            if cy < min_y: min_y = cy
            if cy > max_y: max_y = cy
            if cx < min_x: min_x = cx
            if cx > max_x: max_x = cx
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < sh and 0 <= nx < sw and sub[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))

        bw = (max_x - min_x + 1) * subsample
        bh = (max_y - min_y + 1) * subsample
        if bw >= 15 and bh >= 8:
            blobs.append({"x": min_x * subsample, "y": min_y * subsample,
                          "w": bw, "h": bh})

        if len(blobs) >= max_blobs:
            break

    return blobs


def _find_blobs_pil(binary_img):
    """PIL-only fallback: grid-cell edge-density scan when numpy is absent."""
    w, h = binary_img.size
    cell = 40
    blobs = []
    pix = binary_img.load()

    for gy in range(0, h - cell, cell // 2):
        for gx in range(0, w - cell, cell // 2):
            whites = sum(
                1 for dy in range(cell) for dx in range(cell)
                if 0 <= gy + dy < h and 0 <= gx + dx < w
                and pix[gx + dx, gy + dy] > 128
            )
            density = whites / (cell * cell)
            if 0.05 < density < 0.65:
                blobs.append({"x": gx, "y": gy, "w": cell * 2, "h": cell})

    return blobs


# ---------------------------------------------------------------------------
# Display scale helper
# ---------------------------------------------------------------------------

def _get_display_scale(screen_width):
    """Return scale factor to adapt thresholds for ultrawide / high-res displays."""
    if screen_width > 2560:
        return screen_width / 1920.0
    return 1.0


# ---------------------------------------------------------------------------
# Color analysis + element classification
# ---------------------------------------------------------------------------

def _dominant_color(pil_img):
    """Average color of a region as #rrggbb."""
    try:
        small = pil_img.resize((16, 16)).convert("RGB")
        pixels = list(small.getdata())
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#808080"


def _classify_element(region_img, aspect, w, h, scale=1.0):
    """Return (type_str, confidence 0.0-1.0) based on shape and color."""
    try:
        small = region_img.resize((16, 16)).convert("RGB")
        pixels = list(small.getdata())
        r_avg = sum(p[0] for p in pixels) / len(pixels)
        g_avg = sum(p[1] for p in pixels) / len(pixels)
        b_avg = sum(p[2] for p in pixels) / len(pixels)
    except Exception:
        return "unknown", 0.0

    gray = (r_avg + g_avg + b_avg) / 3
    spread = max(abs(r_avg - gray), abs(g_avg - gray), abs(b_avg - gray))

    # Container: very large region
    if w > 400 * scale and h > 150 * scale:
        return "container", 0.35

    # Icon: small, roughly square
    if w < 60 * scale and h < 60 * scale and 0.5 < aspect < 2.0:
        return "icon", 0.45

    # Input field: near-white background
    if h > 24 * scale and aspect < 10 and w > 60 * scale and gray > 220 and spread < 20:
        return "input", 0.65

    # NVIDIA / Spotify green action button
    if g_avg > max(r_avg, b_avg) * 1.15 and g_avg > 80:
        return "button", 0.78

    # Blue link / secondary button
    if b_avg > max(r_avg, g_avg) * 1.15 and b_avg > 80:
        return "link", 0.68

    # Red danger / cancel button
    if r_avg > max(g_avg, b_avg) * 1.25 and r_avg > 80:
        return "button", 0.68

    # Wide rectangle (2:1 to 20:1 aspect) with sufficient height → button
    if 2.0 <= aspect <= 20.0 and h > 18 * scale:
        conf = 0.72 if aspect <= 10.0 else 0.58
        return "button", conf

    # Low saturation (gray) → button or input depending on shape
    if spread < 18:
        if 1.5 < aspect < 12 and 16 * scale < h < 60 * scale:
            return "button", 0.55
        if h > 20 * scale and w > 80 * scale:
            return "input", 0.45
        return "text", 0.28

    # Moderately wide, moderate height → likely button
    if 1.5 < aspect < 15 and 14 * scale < h < 72 * scale:
        return "button", 0.58

    return "text", 0.22


# ---------------------------------------------------------------------------
# Non-maximum suppression
# ---------------------------------------------------------------------------

def _iou(a, b):
    ax1, ay1 = a["bbox"]["x"], a["bbox"]["y"]
    ax2, ay2 = ax1 + a["bbox"]["w"], ay1 + a["bbox"]["h"]
    bx1, by1 = b["bbox"]["x"], b["bbox"]["y"]
    bx2, by2 = bx1 + b["bbox"]["w"], by1 + b["bbox"]["h"]
    inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0


def _nms_elements(elements, iou_threshold=0.5):
    elements = sorted(elements, key=lambda e: -e["confidence"])
    kept = []
    for elem in elements:
        if all(_iou(elem, k) < iou_threshold for k in kept):
            kept.append(elem)
    return kept


# ---------------------------------------------------------------------------
# Main detection pipeline
# ---------------------------------------------------------------------------

def _detect_elements(pil_img, offset=(0, 0), screen_width=None):
    """Detect button-like UI elements.  Returns list of element dicts."""
    if not _HAS_PIL or pil_img is None:
        return []

    img_w, img_h = pil_img.size
    ox, oy = offset

    # Use full screen width (not region width) for threshold scaling
    scale = _get_display_scale(screen_width if screen_width else img_w)

    binary = _edge_binary(pil_img)
    dilated = _dilate_pil(binary, radius=8)

    if _HAS_NUMPY:
        arr = np.array(dilated, dtype=np.uint8)
        blobs = _find_blobs_numpy(arr, subsample=4)
    else:
        blobs = _find_blobs_pil(dilated)

    elements = []
    for blob in blobs:
        x, y, w, h = blob["x"], blob["y"], blob["w"], blob["h"]

        if w < 20 or h < 10:
            continue
        if w > img_w * 0.90 or h > img_h * 0.90:
            continue

        aspect = w / max(h, 1)
        if aspect < 0.3 or aspect > 25:
            continue

        cx1 = min(max(0, x), img_w - 1)
        cy1 = min(max(0, y), img_h - 1)
        cx2 = min(x + w, img_w)
        cy2 = min(y + h, img_h)
        region = pil_img.crop((cx1, cy1, cx2, cy2))

        elem_type, confidence = _classify_element(region, aspect, w, h, scale=scale)
        elements.append({
            "bbox": {"x": x + ox, "y": y + oy, "w": w, "h": h},
            "type": elem_type,
            "text": "",
            "confidence": confidence,
            "color": _dominant_color(region),
        })

    elements = _nms_elements(elements, iou_threshold=0.5)

    for i, e in enumerate(elements, 1):
        e["id"] = i

    return elements


# ---------------------------------------------------------------------------
# OCR helpers
# ---------------------------------------------------------------------------

def _ocr_image(pil_img):
    """Run Windows OCR on a PIL image; return routes_ocr-style result dict."""
    if _win_ocr_fn:
        return _win_ocr_fn(pil_img)
    return {"success": False, "error": "Windows OCR unavailable (routes_ocr not loaded)",
            "text": "", "words": []}


def _ocr_find_text(pil_img, target_text):
    """Run OCR on the full image and return the bbox [x,y,w,h] of the best
    matching word, or None if not found."""
    result = _ocr_image(pil_img)
    if not result.get("success"):
        return None
    needle = target_text.lower().strip()
    exact = None
    partial = None
    partial_score = 0
    for word in result.get("words", []):
        wtext = word.get("text", "").lower()
        bbox = word.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        if needle == wtext:
            exact = bbox
            break
        if needle in wtext or wtext in needle:
            score = len(wtext)
            if score > partial_score:
                partial_score = score
                partial = bbox
    return exact or partial


def _ocr_elem_text(pil_img, rel_x, rel_y, w, h):
    """OCR a sub-region of pil_img (coordinates relative to pil_img)."""
    img_w, img_h = pil_img.size
    x1 = min(max(0, rel_x), img_w - 1)
    y1 = min(max(0, rel_y), img_h - 1)
    x2 = min(rel_x + w, img_w)
    y2 = min(rel_y + h, img_h)
    if x2 <= x1 or y2 <= y1:
        return ""
    crop = pil_img.crop((x1, y1, x2, y2))
    result = _ocr_image(crop)
    return result.get("text", "").strip() if result.get("success") else ""


# ---------------------------------------------------------------------------
# Color matching helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return None


def _color_distance(hex_a, hex_b):
    a = _hex_to_rgb(hex_a)
    b = _hex_to_rgb(hex_b)
    if not a or not b:
        return 999.0
    return sum((ca - cb) ** 2 for ca, cb in zip(a, b)) ** 0.5


# ---------------------------------------------------------------------------
# Mouse click + window focus
# ---------------------------------------------------------------------------

def _focus_window(window_title):
    try:
        import pygetwindow as gw
        wins = [w for w in gw.getWindowsWithTitle(window_title) if w.title]
        if wins:
            wins[0].activate()
            time.sleep(0.15)
    except Exception:
        pass


def _click_at(screen_x, screen_y):
    """Click at absolute screen coordinates.  Returns True on success."""
    try:
        import pyautogui
        pyautogui.click(screen_x, screen_y)
        return True
    except Exception:
        pass
    try:
        import win32api
        import win32con
        win32api.SetCursorPos((int(screen_x), int(screen_y)))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        return True
    except Exception as e:
        _log(f"[vision] click({screen_x},{screen_y}) failed: {e}")
        return False


def _thumbnail_b64(pil_img, rel_x, rel_y, w, h, pad=12):
    """Return a base64 PNG thumbnail of a region within pil_img."""
    try:
        img_w, img_h = pil_img.size
        x1 = max(0, rel_x - pad)
        y1 = max(0, rel_y - pad)
        x2 = min(img_w, rel_x + w + pad)
        y2 = min(img_h, rel_y + h + pad)
        crop = pil_img.crop((x1, y1, x2, y2))
        return _pil_to_png_b64(crop)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/vision/detect", methods=["POST"])
    @require_auth
    def vision_detect():
        """Find all clickable-looking elements in a screenshot.

        Body (all optional):
          region  — {x, y, w, h} to restrict the search area
          window  — window title to restrict to that window's bounds
          ocr     — true to run Windows OCR on each detected element
        Returns list of {id, bbox:{x,y,w,h}, text, type, confidence, color}.
        """
        d = _json_body()
        if isinstance(d, tuple):
            return d
        region = d.get("region")
        window = (d.get("window") or "").strip() or None
        want_ocr = bool(d.get("ocr", False))

        if not _HAS_PIL:
            return jsonify({"ok": False,
                            "error": "PIL/Pillow not available"}), 500

        t0 = time.time()
        img, offset = _grab_region(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": "Screen capture failed",
                            "code": "CAPTURE_FAILED"}), 500

        try:
            img_w, img_h = img.size

            # For region/window captures the image is smaller than the screen;
            # query the actual monitor width so scale is computed correctly.
            screen_width = img_w
            if region or window:
                try:
                    import mss
                    with mss.mss() as sct:
                        screen_width = sct.monitors[1]["width"]
                except Exception:
                    pass

            elements = _detect_elements(img, offset=offset, screen_width=screen_width)

            if want_ocr:
                ox, oy = offset
                for elem in elements:
                    rel_x = elem["bbox"]["x"] - ox
                    rel_y = elem["bbox"]["y"] - oy
                    elem["text"] = _ocr_elem_text(img, rel_x, rel_y,
                                                  elem["bbox"]["w"], elem["bbox"]["h"])
                # Reclassify elements confirmed to have text as buttons when shape matches
                for elem in elements:
                    if (elem["text"] and
                            elem["bbox"]["w"] > 60 and
                            elem["bbox"]["h"] > 18 and
                            elem["type"] not in ("button", "input")):
                        ar = elem["bbox"]["w"] / max(elem["bbox"]["h"], 1)
                        if 2.0 <= ar <= 20.0:
                            elem["type"] = "button"
                            elem["confidence"] = min(elem["confidence"] + 0.15, 0.85)

            return jsonify({
                "ok": True,
                "count": len(elements),
                "elements": elements,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
                "backend": "numpy+pil" if _HAS_NUMPY else "pil",
                "region": region,
                "window": window,
                "display_info": {"width": img_w, "height": img_h},
            })
        finally:
            try:
                img.close()
            except Exception:
                pass

    @app.route("/vision/click", methods=["POST"])
    @require_auth
    def vision_click():
        """Find and click a button by visual description.

        Body:
          text    — button label to search for via OCR (preferred strategy)
          color   — dominant color hint as #rrggbb (e.g. "#76b900" for NVIDIA green)
          window  — window title to scope the search (also brings window to front)
          region  — {x, y, w, h} to restrict the search area
          type    — "button"|"input"|"link" filter (optional)

        At least one of text or color is required.
        Returns {ok, clicked, method, click_point:{x,y}, element, ...}.
        """
        d = _json_body()
        if isinstance(d, tuple):
            return d
        target_text = (d.get("text") or "").strip()
        target_color = (d.get("color") or "").strip() or None
        window = (d.get("window") or "").strip() or None
        region = d.get("region")
        elem_type_filter = (d.get("type") or "").strip() or None

        if not target_text and not target_color:
            return jsonify({"ok": False,
                            "error": "Provide at least 'text' or 'color' to match"}), 400

        if not _HAS_PIL:
            return jsonify({"ok": False, "error": "PIL/Pillow not available"}), 500

        t0 = time.time()

        if window:
            _focus_window(window)

        img, offset = _grab_region(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": "Screen capture failed",
                            "code": "CAPTURE_FAILED"}), 500

        ox, oy = offset

        try:
            # --- Strategy 1: OCR text match (fast, accurate) ----------------------
            if target_text:
                word_bbox = _ocr_find_text(img, target_text)
                if word_bbox:
                    wx, wy, ww, wh = word_bbox[:4]
                    click_x = ox + wx + ww // 2
                    click_y = oy + wy + wh // 2
                    clicked = _click_at(click_x, click_y)
                    thumb = _thumbnail_b64(img, wx, wy, ww, wh)
                    return jsonify({
                        "ok": clicked,
                        "clicked": clicked,
                        "method": "ocr_text_match",
                        "matched_text": target_text,
                        "click_point": {"x": click_x, "y": click_y},
                        "thumbnail": thumb,
                        "elapsed_ms": round((time.time() - t0) * 1000, 1),
                    })

            # --- Strategy 2: visual detection + color / element scoring -----------
            click_screen_w = img.size[0]
            if region or window:
                try:
                    import mss
                    with mss.mss() as sct:
                        click_screen_w = sct.monitors[1]["width"]
                except Exception:
                    pass
            elements = _detect_elements(img, offset=offset, screen_width=click_screen_w)

            if elem_type_filter:
                typed = [e for e in elements if e["type"] == elem_type_filter]
                if typed:
                    elements = typed

            scored = []
            for elem in elements:
                score = 0.0

                if target_color:
                    dist = _color_distance(elem["color"], target_color)
                    if dist < 30:
                        score += 50
                    elif dist < 70:
                        score += 20
                    elif dist < 120:
                        score += 5

                if target_text:
                    rel_x = elem["bbox"]["x"] - ox
                    rel_y = elem["bbox"]["y"] - oy
                    text = _ocr_elem_text(img, rel_x, rel_y,
                                          elem["bbox"]["w"], elem["bbox"]["h"])
                    elem["text"] = text
                    needle = target_text.lower()
                    haystack = text.lower()
                    if needle == haystack:
                        score += 80
                    elif needle in haystack:
                        score += 55
                    elif any(w in haystack for w in needle.split() if len(w) > 2):
                        score += 20

                if elem["type"] == "button":
                    score += 8
                score += elem["confidence"] * 0.05

                if score > 0:
                    scored.append((score, elem))

            if not scored:
                return jsonify({
                    "ok": False,
                    "error": (f"No element matching text={target_text!r} "
                              f"color={target_color!r} found"),
                    "code": "NOT_FOUND",
                    "elements_searched": len(elements),
                    "elapsed_ms": round((time.time() - t0) * 1000, 1),
                }), 404

            scored.sort(key=lambda x: -x[0])
            best_score, best = scored[0]

            bx = best["bbox"]["x"]
            by = best["bbox"]["y"]
            bw = best["bbox"]["w"]
            bh = best["bbox"]["h"]
            click_x = bx + bw // 2
            click_y = by + bh // 2
            clicked = _click_at(click_x, click_y)

            thumb = _thumbnail_b64(img, bx - ox, by - oy, bw, bh)

            return jsonify({
                "ok": clicked,
                "clicked": clicked,
                "method": "visual_detection",
                "element": best,
                "score": round(best_score, 1),
                "click_point": {"x": click_x, "y": click_y},
                "thumbnail": thumb,
                "candidates": len(scored),
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })
        finally:
            try:
                img.close()
            except Exception:
                pass

    @app.route("/vision/ocr", methods=["POST"])
    @require_auth
    def vision_ocr():
        """OCR a screen region using Windows built-in OCR (Windows.Media.Ocr).

        Body (all optional):
          region  — {x, y, w, h} to restrict the area
          window  — window title to restrict to that window's bounds

        Returns {ok, text, words:[{text, bbox:[x,y,w,h], confidence}], ...}.
        Word bounding boxes are in absolute screen coordinates.
        """
        d = _json_body()
        if isinstance(d, tuple):
            return d
        region = d.get("region")
        window = (d.get("window") or "").strip() or None

        if not _HAS_PIL:
            return jsonify({"ok": False, "error": "PIL/Pillow not available"}), 500

        t0 = time.time()
        img, offset = _grab_region(region=region, window=window)
        if img is None:
            return jsonify({"ok": False, "error": "Screen capture failed",
                            "code": "CAPTURE_FAILED"}), 500

        result = None
        elapsed = 0.0
        try:
            result = _ocr_image(img)
            elapsed = round((time.time() - t0) * 1000, 1)

            if result.get("success"):
                ox, oy = offset
                words = result.get("words", [])
                # Translate word bboxes from image-relative to screen-absolute
                for word in words:
                    bbox = word.get("bbox")
                    if bbox and len(bbox) >= 4:
                        word["bbox"] = [bbox[0] + ox, bbox[1] + oy, bbox[2], bbox[3]]
                return jsonify({
                    "ok": True,
                    "text": result.get("text", ""),
                    "words": words,
                    "word_count": result.get("word_count", len(words)),
                    "line_count": result.get("line_count", 0),
                    "region": region,
                    "window": window,
                    "elapsed_ms": elapsed,
                })

            return jsonify({
                "ok": False,
                "error": result.get("error", "OCR failed"),
                "text": "",
                "words": [],
                "elapsed_ms": elapsed,
            }), 500
        finally:
            try:
                img.close()
            except Exception:
                pass
