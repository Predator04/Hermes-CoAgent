"""Token-efficient structured perception snapshot.

Composes existing primitives (UIA tree, OCR, window layout, dominant colors)
into a single compact, LLM-ready JSON description of the current screen —
without shipping a full-resolution screenshot to a cloud model.

Endpoints:
  GET  /perception/snapshot - compact structured snapshot (no image bytes)
  POST /perception/crop     - tightly-cropped PNG (base64) for a bbox, so a
                              planner can fetch only the ambiguous regions
                              UIA/OCR can't resolve

Windows-only and third-party imports are wrapped in try/except so this file
imports cleanly under a Linux syntax check.
"""

import base64
import io
import time

from flask import jsonify

from shared import _json_body, _log


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

# Control types that a planner can meaningfully act on.
_ACTIONABLE_TYPES = {
    "button", "edit", "checkbox", "radiobutton", "combobox", "listitem",
    "menuitem", "tabitem", "link", "hyperlink", "splitbutton", "togglebutton",
    "slider", "spinbox", "dataitem", "treeitem", "document", "text",
    "header", "headeritem", "menubar", "toolbar", "window", "pane",
    "group", "list", "table", "datagrid", "image", "custom", "menu",
}

_MAX_ELEMENTS = 250


def _window_layout():
    """Visible top-level windows with title, rect, and z-order."""
    out = []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        # Declare signatures so 64-bit HWND/RECT pointers aren't truncated to
        # 32-bit c_int defaults, which silently corrupts handle/pointer values.
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        def cb(hwnd, _lp):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                if not title:
                    return True
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                out.append({
                    "title": title,
                    "hwnd": int(hwnd),
                    "rect": [int(rect.left), int(rect.top),
                             int(rect.right), int(rect.bottom)],
                })
            except Exception:
                pass
            return True

        if not user32.EnumWindows(enum_proc(cb), 0):
            _log("[perception] EnumWindows failed during enumeration")
    except Exception as exc:
        _log(f"[perception] window layout failed: {exc}")
    # EnumWindows enumerates top-down in z-order; encode it explicitly.
    for i, win in enumerate(out):
        win["z"] = i
    return out


def _uia_actionable():
    """Filtered UIA tree: visible elements, flagged actionable, capped."""
    elements = []
    try:
        from routes_uia import _get_uia_engine
        ue = _get_uia_engine()
        snap = ue.uia_snapshot()
        if not snap.get("success"):
            return elements
        tree = snap.get("tree") or {}

        def _bbox(rect):
            if not isinstance(rect, dict):
                return None
            left = rect.get("left", rect.get("x"))
            top = rect.get("top", rect.get("y"))
            width = rect.get("width")
            height = rect.get("height")
            if left is None or top is None or width is None or height is None:
                return None
            try:
                bbox = [int(left), int(top), int(width), int(height)]
            except (TypeError, ValueError):
                return None
            if bbox[2] <= 0 or bbox[3] <= 0:
                return None
            return bbox

        def walk(node, depth=0):
            if depth > 8 or len(elements) >= _MAX_ELEMENTS:
                return
            if not isinstance(node, dict):
                return
            # Skip invisible nodes to keep the snapshot lean.
            if node.get("visible") is False:
                return
            ctype = str(node.get("control_type") or node.get("type") or "").lower()
            name = str(node.get("name") or "").strip()
            actionable = ctype in _ACTIONABLE_TYPES
            if name or actionable:
                elements.append({
                    "role": ctype,
                    "name": name,
                    "automation_id": node.get("automation_id")
                                     or node.get("automationId") or "",
                    "bbox": _bbox(node.get("rect") or node.get("bounding_rect")),
                    "enabled": bool(node.get("enabled", True)),
                    "actionable": actionable,
                })
            for child in node.get("children") or []:
                walk(child, depth + 1)

        walk(tree)
    except Exception as exc:
        _log(f"[perception] UIA filter failed: {exc}")
    return elements


def _ocr_words(pil_img):
    if pil_img is None:
        return []
    try:
        from routes_ocr import _windows_ocr
        result = _windows_ocr(pil_img)
        if not result.get("success"):
            return []
        words = result.get("words") or []
        return [{"text": w.get("text", ""), "bbox": w.get("bbox"),
                 "confidence": w.get("confidence")} for w in words]
    except Exception as exc:
        _log(f"[perception] OCR failed: {exc}")
        return []


def _dominant_colors(pil_img, n=5):
    if pil_img is None:
        return []
    try:
        from collections import Counter
        small = pil_img.convert("RGB").resize((32, 32))
        counter = Counter(small.getdata())
        total = sum(counter.values()) or 1
        return [{"rgb": list(c), "share": round(cnt / total, 4)}
                for c, cnt in counter.most_common(n)]
    except Exception as exc:
        _log(f"[perception] colors failed: {exc}")
        return []


def _screen_img():
    try:
        from routes_ocr import _screen_img as grab
        return grab(force=False)
    except Exception as exc:
        _log(f"[perception] screenshot failed: {exc}")
        return None


def _estimate_tokens(elements, words, windows):
    # Rough heuristic: structured records are far cheaper than vision tokens.
    est = len(elements) * 14 + len(words) * 8
    est += sum((len(w.get("title", "")) + 2) // 3 for w in windows)
    return est


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/perception/snapshot", methods=["GET"])
    @require_auth
    def route_perception_snapshot():
        """Compact, LLM-ready JSON description of the current screen."""
        pil = _screen_img()
        elements = _uia_actionable()
        words = _ocr_words(pil)
        windows = _window_layout()
        colors = _dominant_colors(pil)
        size = list(pil.size) if pil is not None else None
        return jsonify({
            "screen_size": size,
            "window_layout": windows,
            "elements": elements,
            "element_count": len(elements),
            "ocr": words,
            "ocr_word_count": len(words),
            "dominant_colors": colors,
            "token_estimate": _estimate_tokens(elements, words, windows),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @app.route("/perception/crop", methods=["POST"])
    @require_auth
    def route_perception_crop():
        """Return a tightly-cropped PNG (base64) for a bounding box.

        Body: {"bbox": [x, y, width, height], "pad": 0, "quality": "png"}
        """
        body = _json_body() or {}
        bbox = body.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return jsonify({"error": "bbox must be [x, y, width, height]"}), 400
        try:
            x, y, w, h = (int(v) for v in bbox)
        except (TypeError, ValueError):
            return jsonify({"error": "bbox values must be integers"}), 400
        if w <= 0 or h <= 0:
            return jsonify({"error": "bbox width/height must be positive"}), 400

        pil = _screen_img()
        if pil is None:
            return jsonify({"error": "screenshot unavailable"}), 500

        pad = body.get("pad", 0)
        try:
            pad = int(pad)
        except (TypeError, ValueError):
            pad = 0
        pad = max(0, min(pad, 64))

        left = max(0, x - pad)
        top = max(0, y - pad)
        right = min(pil.width, x + w + pad)
        bottom = min(pil.height, y + h + pad)
        if right <= left or bottom <= top:
            return jsonify({"error": "bbox outside screen bounds"}), 400

        crop = pil.crop((left, top, right, bottom))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return jsonify({
            "bbox": [left, top, right - left, bottom - top],
            "requested": [x, y, w, h],
            "mime": "image/png",
            "base64": b64,
        })
