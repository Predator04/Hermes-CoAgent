"""Screen Understanding API.

Vision-first endpoint that captures the full desktop, runs OCR + object detection,
and returns a structured description of what's on screen. Works like a "read the room"
command for agents — get a full picture in a single call instead of many.
"""
import io
import logging
import threading

from flask import Blueprint, jsonify, request

from shared import _self_port, _wrap_registered_blueprint_routes

_LOGGER = logging.getLogger(__name__)
vision_bp = Blueprint("screen_vision", __name__)

_VISION_STATE = {
    "total_describes": 0,
    "total_ocr": 0,
    "total_find": 0,
    "last_method": None,
}
_VISION_LOCK = threading.Lock()


def _debug_failure(context, exc):
    _LOGGER.debug("screen_vision %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _capture_screenshot():
    """Capture screenshot bytes using CoAgent's own /screen endpoint."""
    try:
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{_self_port()}/screen?monitor=0")
        # No auth needed for localhost if auth is disabled, otherwise add token
        try:
            import auth
            token = getattr(auth, "AUTH_TOKEN", "") or ""
            if token:
                req.add_header("Authorization", f"Bearer {token}")
        except ImportError:
            pass
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as exc:
        _debug_failure("capture_screenshot", exc)
        return None


def _describe_via_ocr(screenshot_bytes):
    """Use Windows OCR to extract all text, then summarize."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(screenshot_bytes))
        from routes_ocr import _windows_ocr
        ocr_result = _windows_ocr(img)
        if ocr_result.get("success"):
            text = ocr_result.get("text", "")
            lines = [l.strip() for l in text.split() if l.strip()]
            # Extract key UI elements from text
            ui_elements = _parse_ui_from_text(lines)
            return {
                "success": True,
                "method": "windows_ocr",
                "text_snippet": " ".join(lines[:50]),
                "total_words": ocr_result.get("word_count", 0),
                "total_lines": ocr_result.get("line_count", 0),
                "ui_elements": ui_elements,
            }
    except Exception as exc:
        _debug_failure("describe_via_ocr", exc)

    return {"success": False, "error": "OCR unavailable"}


def _parse_ui_from_text(words):
    """Try to extract UI element names from OCR output."""
    elements = []
    # Common UI patterns: buttons, labels, menu items
    ui_keywords = ["file", "edit", "view", "help", "settings", "search", 
                   "save", "open", "close", "exit", "cancel", "apply", "ok",
                   "yes", "no", "submit", "next", "back", "done", "browse",
                   "browser", "notepad", "calculator", "settings", "control"]
    seen = set()
    for w in words:
        clean = w.strip(".,:;!?\"'()[]{}").lower()
        if clean and len(clean) > 1 and clean not in seen:
            seen.add(clean)
            if clean in ui_keywords:
                elements.append({"text": w.strip(".,:;!?\"'()[]{}"), "type": "button"})
    return elements


def _find_on_screen(query, screenshot_bytes):
    """Find text on screen and return positions."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(screenshot_bytes))
        from routes_ocr import ocr_find_text
        matches = ocr_find_text(query, img)
        return matches
    except Exception as exc:
        _debug_failure("find_on_screen", exc)
        return []


def _screen_region_brief(screenshot_bytes):
    """Return a quick description of what's on screen."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(screenshot_bytes))
        w, h = img.size
        dominant_colors = _get_dominant_colors(img)
        return {
            "dimensions": f"{w}x{h}",
            "aspect": f"{w/h:.2f}" if h else "?",
            "dominant_colors": dominant_colors,
        }
    except Exception:
        return {"error": "could not analyze"}


def _get_dominant_colors(img, num=3):
    """Sample the image and find dominant color ranges."""
    try:
        small = img.convert("RGB").resize((32, 32))
        pixels = list(small.getdata())
        # Rough color quantization
        buckets = {}
        for r, g, b in pixels[:256]:
            key = (r // 64, g // 64, b // 64)
            buckets[key] = buckets.get(key, 0) + 1
        sorted_buckets = sorted(buckets.items(), key=lambda x: -x[1])[:num]
        color_names = []
        for (br, bg, bb), count in sorted_buckets:
            r_mid = br * 64 + 32
            g_mid = bg * 64 + 32
            b_mid = bb * 64 + 32
            name = _color_name(r_mid, g_mid, b_mid)
            color_names.append({"color": name, "rgb": [r_mid, g_mid, b_mid], "pct": round(count / len(pixels) * 100, 1)})
        return color_names
    except Exception:
        return []


def _color_name(r, g, b):
    if r > 200 and g > 200 and b > 200:
        return "white"
    if r < 50 and g < 50 and b < 50:
        return "black"
    if r > 200 and g < 100 and b < 100:
        return "red"
    if r < 100 and g > 200 and b < 100:
        return "green"
    if r < 100 and g < 100 and b > 200:
        return "blue"
    if r > 200 and g > 200 and b < 100:
        return "yellow"
    if r < 100 and g > 150 and b > 200:
        return "cyan"
    if abs(r - g) < 30 and abs(g - b) < 30:
        return f"gray({(r+g+b)//3})"
    return f"rgb({r},{g},{b})"


@vision_bp.route("/vision/describe", methods=["POST"])
def _vision_describe():
    """Full desktop description in one call."""
    body = request.get_json(force=True, silent=True) or {}
    screenshot = _capture_screenshot()
    if not screenshot:
        return jsonify({"ok": False, "error": "Cannot capture screen"}), 500

    ocr = _describe_via_ocr(screenshot)
    region = _screen_region_brief(screenshot)

    from PIL import Image
    img = Image.open(io.BytesIO(screenshot))
    w, h = img.size

    result = {
        "ok": ocr.get("success", False),
        "screen_size": f"{w}x{h}",
        "ocr": {
            "text": ocr.get("text_snippet", ""),
            "total_words": ocr.get("total_words", 0),
            "total_lines": ocr.get("total_lines", 0),
        },
        "ui_elements": ocr.get("ui_elements", []),
        "visual": region,
        "method": ocr.get("method", "none"),
    }

    with _VISION_LOCK:
        _VISION_STATE["total_describes"] += 1
        _VISION_STATE["last_method"] = ocr.get("method")

    return jsonify(result)


@vision_bp.route("/vision/find", methods=["POST"])
def _vision_find():
    """Find text on screen and return positions with context."""
    body = request.get_json(force=True, silent=True) or {}
    query = body.get("query", "")
    if not query:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400

    screenshot = _capture_screenshot()
    if not screenshot:
        return jsonify({"ok": False, "error": "Cannot capture screen"}), 500

    matches = _find_on_screen(query, screenshot)
    context_regions = []

    # If we found matches, also grab surrounding text for context
    if matches:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(screenshot))
            from routes_ocr import _windows_ocr
            full_ocr = _windows_ocr(img)
            if full_ocr.get("success"):
                context_regions = full_ocr.get("text", "")[:500]
        except Exception:
            pass

    with _VISION_LOCK:
        _VISION_STATE["total_find"] += 1

    return jsonify({
        "ok": len(matches) > 0,
        "query": query,
        "matches": matches,
        "count": len(matches),
        "context": context_regions if context_regions else None,
    })


@vision_bp.route("/vision/status", methods=["GET"])
def _vision_status():
    with _VISION_LOCK:
        return jsonify({"ok": True, **_VISION_STATE})


@vision_bp.route("/vision/quick-scan", methods=["GET"])
def _vision_quick_scan():
    """Lightning-fast screen check: what's open right now?"""
    try:
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{_self_port()}/screen?monitor=0")
        try:
            import auth
            token = getattr(auth, "AUTH_TOKEN", "") or ""
            if token:
                req.add_header("Authorization", f"Bearer {token}")
        except ImportError:
            pass
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if not data:
            return jsonify({"ok": False, "error": "empty screenshot"}), 500

        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        from routes_ocr import _windows_ocr
        ocr = _windows_ocr(img)
        lines = ocr.get("text", "").split()[:30] if ocr.get("success") else []

        return jsonify({
            "ok": True,
            "resolution": f"{w}x{h}",
            "visible_text": " ".join(lines),
            "app_suggestions": _parse_ui_from_text(lines),
        })
    except Exception as exc:
        _debug_failure("quick_scan", exc)
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


def register_routes(app, state, require_auth):
    app.register_blueprint(vision_bp)
    if require_auth:
        _wrap_registered_blueprint_routes(app, vision_bp.name, require_auth)
    _LOGGER.info("Screen Understanding API routes registered")
