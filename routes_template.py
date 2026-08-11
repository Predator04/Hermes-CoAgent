"""Template-matching automation for apps where CDP/UIA cannot reach internal elements.

Works by:
  1. Taking a screenshot of the full screen (or a restricted window/region).
  2. Running OpenCV TM_CCOEFF_NORMED multi-scale template matching.
  3. Deduplicating results via non-maximum suppression (NMS).
  4. Clicking the best match using pyautogui / Win32 mouse_event.

Ideal for CEF apps (NVIDIA App, Spotify, Discord, Steam) where CDP debugging
is blocked and UIA cannot see sub-elements.

Endpoints:
  POST /template/save          — persist a named template PNG to disk
  GET  /template/list          — list saved templates
  POST /template/delete        — remove a saved template
  POST /template/capture       — capture a screen region and save/return it as a template
  POST /template/find          — locate a template on screen, return matches
  POST /template/click         — find best match and click it
  POST /template/smart-click   — one-shot: inline or named template + optional window scoping
"""

import base64
import io
import re
import threading
from pathlib import Path

from flask import jsonify, request
from shared import COAGENT_DIR, _json_body, _log

# ---------------------------------------------------------------------------
# Template storage
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = COAGENT_DIR / "templates"
_TEMPLATES_DIR.mkdir(exist_ok=True)

_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# OpenCV availability check
# ---------------------------------------------------------------------------

def _require_cv2():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        return None, None


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def _grab_screen_cv2(region=None):
    """Return (numpy BGR array, (width, height)) for the screen or a sub-region.

    region — (x, y, w, h) in screen coordinates, or None for the primary monitor.
    """
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            if region:
                x, y, w, h = region
                mon = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
            else:
                mon = sct.monitors[1]   # index 1 = first real monitor (0 = virtual all)
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
    except Exception:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        if region:
            x, y, w, h = region
            img = img.crop((x, y, x + w, y + h))

    import cv2
    import numpy as np
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    return arr, img.size


# ---------------------------------------------------------------------------
# Window bounding-box lookup (Windows)
# ---------------------------------------------------------------------------

def _window_region(window_hint: str):
    """Return (x, y, w, h) screen rect for the first visible window whose
    title contains *window_hint* (case-insensitive). Returns None on failure."""
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        hint = window_hint.lower()
        result = [None]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _lp):
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if hint in buf.value.lower():
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 0 and h > 0:
                    result[0] = (rect.left, rect.top, w, h)
                    return False   # stop enumeration
            return True

        user32.EnumWindows(_cb, 0)
        return result[0]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Template loaders
# ---------------------------------------------------------------------------

def _load_template_name(name: str):
    """Load a saved template as numpy BGR array."""
    import cv2
    path = _TEMPLATES_DIR / f"{name}.png"
    if not path.exists():
        raise FileNotFoundError(f"Template '{name}' not found (expected {path})")
    arr = cv2.imread(str(path))
    if arr is None:
        raise ValueError(f"Failed to decode template image: {path}")
    return arr


def _load_template_b64(b64: str):
    """Decode a base64 image string (any format) to numpy BGR array."""
    import cv2
    import numpy as np
    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode base64 image — must be PNG, JPEG, or BMP")
    return img


# ---------------------------------------------------------------------------
# Non-maximum suppression
# ---------------------------------------------------------------------------

def _nms(matches: list, iou_threshold: float = 0.4) -> list:
    """Remove overlapping matches, keeping the highest-confidence one per cluster."""
    if not matches:
        return []
    matches = sorted(matches, key=lambda m: m["confidence"], reverse=True)
    kept = []
    for m in matches:
        mx = m["x"] - m["w"] // 2
        my = m["y"] - m["h"] // 2
        mw, mh = m["w"], m["h"]
        dup = False
        for k in kept:
            kx = k["x"] - k["w"] // 2
            ky = k["y"] - k["h"] // 2
            kw, kh = k["w"], k["h"]
            ix = max(0, min(mx + mw, kx + kw) - max(mx, kx))
            iy = max(0, min(my + mh, ky + kh) - max(my, ky))
            inter = ix * iy
            union = mw * mh + kw * kh - inter
            if union > 0 and inter / union > iou_threshold:
                dup = True
                break
        if not dup:
            kept.append(m)
    return kept


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

_DEFAULT_SCALES = [1.0, 0.9, 0.8, 1.1, 1.2, 0.75, 1.25]


def _match_template(
    tpl_arr,
    screen_arr,
    threshold: float = 0.8,
    scales=None,
    screen_offset=(0, 0),
) -> list:
    """Multi-scale TM_CCOEFF_NORMED matching. Returns NMS-filtered matches.

    screen_offset — (dx, dy) added to all returned x/y so they are in screen
    coordinates even when screen_arr is a cropped region.
    """
    import cv2
    import numpy as np

    if scales is None:
        scales = _DEFAULT_SCALES

    th, tw = tpl_arr.shape[:2]
    sh, sw = screen_arr.shape[:2]
    dx, dy = screen_offset

    raw = []
    for scale in scales:
        sw2 = max(1, int(tw * scale))
        sh2 = max(1, int(th * scale))
        if sw2 > sw or sh2 > sh or sw2 < 8 or sh2 < 8:
            continue
        tpl_scaled = cv2.resize(tpl_arr, (sw2, sh2))
        res = cv2.matchTemplate(screen_arr, tpl_scaled, cv2.TM_CCOEFF_NORMED)
        locs = np.where(res >= threshold)
        for pt in zip(*locs[::-1]):
            cx = int(pt[0] + sw2 // 2) + dx
            cy = int(pt[1] + sh2 // 2) + dy
            conf = float(res[pt[1], pt[0]])
            raw.append({
                "x": cx, "y": cy,
                "w": sw2, "h": sh2,
                "confidence": round(conf, 4),
                "scale": round(scale, 2),
            })

    return _nms(raw)


# ---------------------------------------------------------------------------
# Mouse click (pyautogui → Win32 fallback)
# ---------------------------------------------------------------------------

def _click(x: int, y: int) -> None:
    try:
        import pyautogui
        pyautogui.click(x, y)
        return
    except Exception:
        pass
    try:
        import ctypes
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        nx = int(x * 65535 / sw)
        ny = int(y * 65535 / sh)
        F = ctypes.windll.user32.mouse_event
        F(0x8001, nx, ny, 0, 0)   # MOVE + ABSOLUTE
        F(0x0002, 0, 0, 0, 0)     # LEFTDOWN
        F(0x0004, 0, 0, 0, 0)     # LEFTUP
    except Exception as exc:
        raise RuntimeError(f"All click backends failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Shared: resolve template + region from request body
# ---------------------------------------------------------------------------

def _resolve_template(body: dict):
    """Return numpy BGR array from 'name' or 'image' key in body."""
    name = (body.get("name") or "").strip()
    b64 = body.get("image", "")
    if name:
        return _load_template_name(name), name
    elif b64:
        return _load_template_b64(b64), "(inline)"
    raise ValueError("Provide 'name' (saved template) or 'image' (base64 PNG/JPEG)")


def _resolve_region(body: dict):
    """Return (capture_region, screen_offset, window_found).

    capture_region — (x, y, w, h) passed to _grab_screen_cv2, or None.
    screen_offset  — (dx, dy) added to match coordinates.
    window_found   — str name of window if it was resolved, else None.
    """
    window = (body.get("window") or "").strip()
    region_raw = body.get("region")

    if window:
        r = _window_region(window)
        if r:
            return r, (r[0], r[1]), window
        _log(f"[TEMPLATE] window '{window}' not found — searching full screen")
        return None, (0, 0), None

    if region_raw:
        try:
            x, y, w, h = [int(v) for v in region_raw[:4]]
            return (x, y, w, h), (x, y), None
        except (TypeError, IndexError, ValueError):
            pass

    return None, (0, 0), None


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    # ------------------------------------------------------------------
    # /template/save
    # ------------------------------------------------------------------

    @app.route("/template/save", methods=["POST"])
    @require_auth
    def template_save():
        """Save a named template image for reuse in later find/click calls.

        Body:
          {
            "name":  "download_button",   — alphanumeric, dashes/underscores ok
            "image": "<base64 PNG/JPEG>"  — image data to save
          }

        Returns: {"saved": true, "name": "...", "path": "...", "width": N, "height": N}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        name = (body.get("name") or "").strip()
        b64 = body.get("image", "")
        if not name:
            return jsonify({"error": "name required"}), 400
        if not b64:
            return jsonify({"error": "image (base64) required"}), 400
        if not re.match(r'^[\w\-]+$', name):
            return jsonify({"error": "name must be alphanumeric with - or _ only"}), 400

        try:
            raw = base64.b64decode(b64)
        except Exception:
            return jsonify({"error": "Invalid base64 data"}), 400

        path = _TEMPLATES_DIR / f"{name}.png"
        try:
            from PIL import Image as _PilImage
            img = _PilImage.open(io.BytesIO(raw)).convert("RGBA")
            img.save(str(path), "PNG")
            w, h = img.size
        except Exception as exc:
            return jsonify({"error": f"Image decode failed: {exc}"}), 400

        _log(f"[TEMPLATE] saved '{name}' → {path} ({w}x{h})")
        return jsonify({
            "saved": True,
            "name": name,
            "path": str(path),
            "width": w,
            "height": h,
            "size_bytes": path.stat().st_size,
        })

    # ------------------------------------------------------------------
    # /template/list
    # ------------------------------------------------------------------

    @app.route("/template/list", methods=["GET", "POST"])
    @require_auth
    def template_list():
        """List all saved template images.

        Returns: {"templates": [...], "count": N}
        """
        cv2, _ = _require_cv2()
        items = []
        for p in sorted(_TEMPLATES_DIR.glob("*.png")):
            entry = {
                "name": p.stem,
                "path": str(p),
                "size_bytes": p.stat().st_size,
                "width": 0,
                "height": 0,
            }
            if cv2:
                arr = cv2.imread(str(p))
                if arr is not None:
                    entry["height"], entry["width"] = arr.shape[:2]
            items.append(entry)
        return jsonify({"templates": items, "count": len(items)})

    # ------------------------------------------------------------------
    # /template/delete
    # ------------------------------------------------------------------

    @app.route("/template/delete", methods=["POST"])
    @require_auth
    def template_delete():
        """Delete a saved template by name.

        Body: {"name": "download_button"}
        Returns: {"deleted": true, "name": "..."}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400

        path = _TEMPLATES_DIR / f"{name}.png"
        if not path.exists():
            return jsonify({"error": f"Template '{name}' not found"}), 404

        path.unlink()
        _log(f"[TEMPLATE] deleted '{name}'")
        return jsonify({"deleted": True, "name": name})

    # ------------------------------------------------------------------
    # /template/capture
    # ------------------------------------------------------------------

    @app.route("/template/capture", methods=["POST"])
    @require_auth
    def template_capture():
        """Capture a screen region and optionally save it as a named template.

        Body:
          {
            "region": [x, y, w, h],   — required: screen region to capture
            "name":   "my_button"     — optional: save as this template name
          }

        Returns: {"image": "<base64 PNG>", "width": N, "height": N, "saved": bool}
        This lets you create templates programmatically without a separate screenshot tool.
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        region_raw = body.get("region")
        if not region_raw:
            return jsonify({"error": "region [x, y, w, h] required"}), 400
        try:
            x, y, w, h = [int(v) for v in region_raw[:4]]
        except (TypeError, IndexError, ValueError):
            return jsonify({"error": "region must be [x, y, w, h] integers"}), 400

        try:
            _, screen_size = _grab_screen_cv2((x, y, w, h))
        except Exception as exc:
            return jsonify({"error": f"Screenshot failed: {exc}"}), 500

        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        except Exception:
            try:
                import mss
                from PIL import Image as _PilImg
                with mss.mss() as sct:
                    raw = sct.grab({"left": x, "top": y, "width": w, "height": h})
                    img = _PilImg.frombytes("RGB", raw.size, raw.rgb)
            except Exception as exc:
                return jsonify({"error": f"Capture failed: {exc}"}), 500

        buf = io.BytesIO()
        img.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        name = (body.get("name") or "").strip()
        saved = False
        if name and re.match(r'^[\w\-]+$', name):
            path = _TEMPLATES_DIR / f"{name}.png"
            img.save(str(path), "PNG")
            saved = True
            _log(f"[TEMPLATE] captured and saved '{name}' ({img.width}x{img.height})")

        return jsonify({
            "image": b64,
            "width": img.width,
            "height": img.height,
            "saved": saved,
            "name": name if saved else None,
        })

    # ------------------------------------------------------------------
    # /template/find
    # ------------------------------------------------------------------

    @app.route("/template/find", methods=["POST"])
    @require_auth
    def template_find():
        """Find a template image on the screen using multi-scale template matching.

        Body:
          {
            "name":        "download_button",  — use a saved template (alt to 'image')
            "image":       "<base64>",          — inline template image (alt to 'name')
            "threshold":   0.8,                 — confidence threshold 0.0–1.0 (default 0.8)
            "window":      "NVIDIA App",        — restrict search to this window title
            "region":      [x, y, w, h],       — restrict search to pixel region
            "scales":      [0.8, 1.0, 1.2],    — override scale search list
            "max_results": 10                   — cap number of returned matches
          }

        Returns:
          {
            "found": true,
            "count": 2,
            "best":    {"x": 940, "y": 512, "w": 120, "h": 40, "confidence": 0.95, "scale": 1.0},
            "matches": [...]
          }
        Coordinates are always in full-screen space (not relative to window/region).
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not installed. Run: pip install opencv-python-headless"}), 500

        try:
            tpl_arr, tpl_label = _resolve_template(body)
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

        threshold = max(0.1, min(0.99, float(body.get("threshold", 0.8))))
        max_results = int(body.get("max_results", 10))
        scales_raw = body.get("scales")
        scales = [float(s) for s in scales_raw] if scales_raw else None

        capture_region, screen_offset, window_found = _resolve_region(body)

        try:
            screen_arr, screen_size = _grab_screen_cv2(capture_region)
        except Exception as exc:
            return jsonify({"error": f"Screenshot failed: {exc}"}), 500

        try:
            matches = _match_template(tpl_arr, screen_arr, threshold, scales, screen_offset)
        except Exception as exc:
            _log(f"[TEMPLATE] find error: {exc}")
            return jsonify({"error": str(exc)}), 500

        matches = matches[:max_results]
        return jsonify({
            "found": bool(matches),
            "count": len(matches),
            "best": matches[0] if matches else None,
            "matches": matches,
            "template": tpl_label,
            "threshold": threshold,
            "window_resolved": window_found,
            "screen_size": list(screen_size),
        })

    # ------------------------------------------------------------------
    # /template/click
    # ------------------------------------------------------------------

    @app.route("/template/click", methods=["POST"])
    @require_auth
    def template_click():
        """Find the best template match on screen and click it.

        Body: same as /template/find, plus:
          {
            "offset_x": 0,      — pixel offset added to match center before clicking
            "offset_y": 0
          }

        Returns:
          {"clicked": true, "x": 940, "y": 512, "confidence": 0.94, "template": "..."}
        On no match: 404 with "clicked": false.
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not installed. Run: pip install opencv-python-headless"}), 500

        try:
            tpl_arr, tpl_label = _resolve_template(body)
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

        threshold = max(0.1, min(0.99, float(body.get("threshold", 0.8))))
        scales_raw = body.get("scales")
        scales = [float(s) for s in scales_raw] if scales_raw else None
        offset_x = int(body.get("offset_x", 0))
        offset_y = int(body.get("offset_y", 0))

        capture_region, screen_offset, window_found = _resolve_region(body)

        try:
            screen_arr, _ = _grab_screen_cv2(capture_region)
        except Exception as exc:
            return jsonify({"error": f"Screenshot failed: {exc}"}), 500

        try:
            matches = _match_template(tpl_arr, screen_arr, threshold, scales, screen_offset)
        except Exception as exc:
            _log(f"[TEMPLATE] click match error: {exc}")
            return jsonify({"error": str(exc)}), 500

        if not matches:
            return jsonify({
                "clicked": False,
                "error": f"Template not found on screen (threshold={threshold})",
                "template": tpl_label,
            }), 404

        best = matches[0]
        cx = best["x"] + offset_x
        cy = best["y"] + offset_y

        try:
            _click(cx, cy)
        except Exception as exc:
            return jsonify({"error": f"Click failed: {exc}", "x": cx, "y": cy}), 500

        _log(f"[TEMPLATE] click '{tpl_label}' → ({cx}, {cy}) conf={best['confidence']}")
        return jsonify({
            "clicked": True,
            "x": cx,
            "y": cy,
            "confidence": best["confidence"],
            "scale": best["scale"],
            "template": tpl_label,
            "window_resolved": window_found,
        })

    # ------------------------------------------------------------------
    # /template/smart-click
    # ------------------------------------------------------------------

    @app.route("/template/smart-click", methods=["POST"])
    @require_auth
    def template_smart_click():
        """One-shot: provide a template (saved name or inline base64), restrict search
        to a named window, and click the best match — all in a single call.

        This is the primary endpoint for CEF app automation when CDP is blocked.

        Body:
          {
            "window":    "NVIDIA App",      — window title to search within (optional)
            "name":      "download_button", — saved template name (alt to 'image')
            "image":     "<base64>",        — inline template (alt to 'name')
            "threshold": 0.8,              — optional, default 0.8
            "offset_x":  0,                — pixel offset from match center
            "offset_y":  0
          }

        Returns:
          {
            "clicked": true,
            "x": 940, "y": 512,
            "confidence": 0.94,
            "window": "NVIDIA App",
            "window_region": [x, y, w, h],
            "template": "download_button"
          }
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body

        cv2, _ = _require_cv2()
        if cv2 is None:
            return jsonify({"error": "OpenCV not installed. Run: pip install opencv-python-headless"}), 500

        try:
            tpl_arr, tpl_label = _resolve_template(body)
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 404

        threshold = max(0.1, min(0.99, float(body.get("threshold", 0.8))))
        offset_x = int(body.get("offset_x", 0))
        offset_y = int(body.get("offset_y", 0))
        window = (body.get("window") or "").strip()

        capture_region, screen_offset, window_found = _resolve_region(body)

        try:
            screen_arr, screen_size = _grab_screen_cv2(capture_region)
        except Exception as exc:
            return jsonify({"error": f"Screenshot failed: {exc}"}), 500

        try:
            matches = _match_template(tpl_arr, screen_arr, threshold, None, screen_offset)
        except Exception as exc:
            _log(f"[TEMPLATE] smart-click error: {exc}")
            return jsonify({"error": str(exc)}), 500

        if not matches:
            return jsonify({
                "clicked": False,
                "error": "Template not found on screen",
                "window": window,
                "window_region": list(capture_region) if capture_region else None,
                "template": tpl_label,
                "threshold": threshold,
            }), 404

        best = matches[0]
        cx = best["x"] + offset_x
        cy = best["y"] + offset_y

        try:
            _click(cx, cy)
        except Exception as exc:
            return jsonify({"error": f"Click failed: {exc}"}), 500

        _log(f"[TEMPLATE] smart-click '{tpl_label}' in '{window}' → ({cx}, {cy}) conf={best['confidence']}")
        return jsonify({
            "clicked": True,
            "x": cx,
            "y": cy,
            "confidence": best["confidence"],
            "scale": best["scale"],
            "window": window,
            "window_region": list(capture_region) if capture_region else None,
            "template": tpl_label,
        })
