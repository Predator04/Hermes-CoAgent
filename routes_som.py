"""
SOM (Set-of-Mark) routes — annotate screen elements with numbered boxes,
click by number, and read element details.

AI agent flow:
  1. POST /som/annotate  → base64 image with numbered boxes + JSON element map
  2. POST /som/click     → {"number": N} → clicks center of element N
  3. POST /som/read      → {"number": N} → returns full properties of element N

This collapses screenshot→analyze→click into 2 HTTP calls.
"""
import base64
import time
import threading
from io import BytesIO
from flask import jsonify, request
from shared import _json_body, _log

HAS_PIL = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    pass

# Server-side SOM cache: preserves element map between annotate and click calls.
_SOM_STATE = {}
_SOM_STATE_LOCK = threading.Lock()
_SOM_STATE_TTL = 300  # 5 minutes

INTERACTIVE_CONTROL_TYPES = {
    "button", "edit", "checkbox", "radiobutton", "combobox",
    "listitem", "menuitem", "tabitem", "link", "hyperlink",
    "splitbutton", "togglebutton", "slider", "spinbox",
    "dataitem", "treeitem",
}

_BOX_COLORS = [
    (220, 53, 69),   # red
    (40, 167, 69),   # green
    (0, 123, 255),   # blue
    (255, 140, 0),   # orange
    (111, 66, 193),  # purple
    (23, 162, 184),  # cyan
    (255, 193, 7),   # yellow (dark text)
]


def _make_error(error, detail="", suggestion="", code="ERROR"):
    return {
        "ok": False,
        "error": error,
        "detail": detail,
        "suggestion": suggestion,
        "code": code,
    }


def _annotate_image(pil_img, elements):
    """Draw numbered bounding boxes on a copy of the image."""
    img = pil_img.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
        label_font = ImageFont.truetype("arialbd.ttf", 12)
    except Exception:
        try:
            font = ImageFont.load_default()
            label_font = font
        except Exception:
            return img

    for i, elem in enumerate(elements, 1):
        bbox = elem.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x, y, w, h = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        if w <= 0 or h <= 0:
            continue

        color = _BOX_COLORS[(i - 1) % len(_BOX_COLORS)]
        # Bounding box outline (2px)
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
        # Label badge above top-left corner
        label = str(i)
        badge_w, badge_h = 22, 18
        bx = max(0, x)
        by = max(0, y - badge_h)
        draw.rectangle([bx, by, bx + badge_w, by + badge_h], fill=color)
        draw.text((bx + 3, by + 2), label, fill="white", font=label_font)

    return img


def _collect_uia_elements(ue, monitor_index=0):
    """Walk UIA accessibility tree and collect interactive elements with positions."""
    elements = []
    try:
        snap = ue.uia_snapshot(timeout=5)
    except Exception as exc:
        _log(f"[som] UIA snapshot failed: {exc}")
        return elements

    if not snap.get("success"):
        return elements

    def walk(node, depth=0):
        if not isinstance(node, dict) or depth > 10:
            return
        rect = node.get("rect") or {}
        try:
            x = int(rect.get("left", rect.get("x", -1)))
            y = int(rect.get("top", rect.get("y", -1)))
            w = int(rect.get("width", 0))
            h = int(rect.get("height", 0))
        except (TypeError, ValueError):
            x = y = w = h = -1

        ctrl = str(node.get("control_type", "")).lower().strip()
        # Strip "controltype." prefix some UIA engines emit
        if "." in ctrl:
            ctrl = ctrl.rsplit(".", 1)[-1]

        name = str(node.get("name") or "").strip()
        enabled = node.get("is_enabled", True)

        if w > 3 and h > 3 and x >= 0 and y >= 0 and name:
            if ctrl in INTERACTIVE_CONTROL_TYPES or (ctrl == "text" and len(name) < 120):
                elements.append({
                    "text": name,
                    "bbox": [x, y, w, h],
                    "center": {"x": x + w // 2, "y": y + h // 2},
                    "type": ctrl or "unknown",
                    "automation_id": node.get("automation_id", ""),
                    "class_name": node.get("class_name", ""),
                    "enabled": bool(enabled),
                })

        for child in node.get("children", []) or []:
            walk(child, depth + 1)

    root = snap.get("tree") or {}
    for child in root.get("children", []) or []:
        walk(child)

    # Deduplicate by (text, bbox) to avoid explosion from mirrored trees
    seen = set()
    unique = []
    for e in elements:
        key = (e["text"], tuple(e["bbox"]))
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _collect_ocr_elements():
    """OCR-based fallback element collection when UIA is unavailable."""
    elements = []
    try:
        import pytesseract
        from routes_ocr import _screen_img
        img = _screen_img(force=True)
        if img is None:
            return elements
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        texts = data.get("text", [])
        for i, text in enumerate(texts):
            text = str(text or "").strip()
            if not text:
                continue
            try:
                x = int(data["left"][i])
                y = int(data["top"][i])
                w = int(data["width"][i])
                h = int(data["height"][i])
                conf = float(data["conf"][i]) if data["conf"][i] != -1 else 0.0
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            if w > 5 and h > 5 and conf > 30:
                elements.append({
                    "text": text,
                    "bbox": [x, y, w, h],
                    "center": {"x": x + w // 2, "y": y + h // 2},
                    "type": "text",
                    "confidence": round(conf, 1),
                })
    except ImportError:
        pass
    except Exception as exc:
        _log(f"[som] OCR element collection failed: {exc}")
    return elements


def _save_som_state(elements):
    now = time.time()
    # Purge stale entries
    stale = [k for k, v in _SOM_STATE.items() if now - v.get("ts", 0) > _SOM_STATE_TTL]
    for k in stale:
        del _SOM_STATE[k]
    element_map = {str(i): elem for i, elem in enumerate(elements, 1)}
    _SOM_STATE["default"] = {"elements": element_map, "ts": now}
    return element_map


def _load_som_state():
    entry = _SOM_STATE.get("default")
    if entry and (time.time() - entry.get("ts", 0)) < _SOM_STATE_TTL:
        return entry["elements"]
    return None


def register_routes(app, state, require_auth):
    # Lazy-load UIA engine — may not be available in all environments
    _ue_cache = [None]

    def _get_ue():
        if _ue_cache[0] is None:
            try:
                from routes_uia import _get_uia_engine
                _ue_cache[0] = _get_uia_engine()
            except Exception as exc:
                _log(f"[som] UIA engine unavailable: {exc}")
        return _ue_cache[0]

    @app.route("/som/annotate", methods=["POST"])
    @require_auth
    def route_som_annotate():
        """
        Screenshot + find interactive elements + draw numbered boxes.
        Returns base64 annotated image and JSON map of number→element.
        Cache is stored server-side so /som/click works without re-annotating.
        """
        if not HAS_PIL:
            return jsonify(_make_error(
                "PIL not available",
                "Pillow is required for SOM annotation",
                "pip install Pillow",
                "PIL_MISSING",
            )), 500

        d = _json_body()
        try:
            monitor_index = int(d.get("monitor") or 0)
        except (TypeError, ValueError):
            monitor_index = 0
        use_ocr_fallback = bool(d.get("ocr_fallback", True))

        # Capture screenshot
        t0 = time.time()
        try:
            from routes_ocr import _capture_raw, _coerce_monitor_index
            monitor_index = _coerce_monitor_index(monitor_index)
            raw = _capture_raw(force=True, monitor_index=monitor_index)
        except Exception as exc:
            return jsonify(_make_error(
                "Screenshot failed",
                f"{type(exc).__name__}: {exc}",
                "Try GET /screen/probe to diagnose screen capture backends",
                "SCREENSHOT_FAILED",
            )), 500

        if not raw:
            return jsonify(_make_error(
                "No screenshot data",
                "Screen capture returned empty bytes",
                "Check GET /screen/probe and GET /screen/diag",
                "EMPTY_SCREENSHOT",
            )), 500

        # Collect interactive elements
        ue = _get_ue()
        elements = []
        uia_ok = False
        if ue is not None:
            elements = _collect_uia_elements(ue, monitor_index)
            uia_ok = bool(elements)

        if not elements and use_ocr_fallback:
            _log("[som] UIA returned no elements — falling back to OCR")
            elements = _collect_ocr_elements()

        if not elements:
            return jsonify(_make_error(
                "No elements found",
                "Neither UIA nor OCR found interactive elements on screen",
                "Ensure a window with UI elements is visible, or check /uia/diag",
                "NO_ELEMENTS",
            )), 404

        # Draw annotated image
        try:
            pil_img = Image.open(BytesIO(raw)).convert("RGB")
            annotated = _annotate_image(pil_img, elements)
            buf = BytesIO()
            annotated.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception as exc:
            return jsonify(_make_error(
                "Image annotation failed",
                f"{type(exc).__name__}: {exc}",
                "Elements were found but drawing boxes failed; check Pillow installation",
                "ANNOTATION_FAILED",
            )), 500

        # Cache and build response
        with _SOM_STATE_LOCK:
            element_map = _save_som_state(elements)

        elapsed_ms = round((time.time() - t0) * 1000, 1)

        return jsonify({
            "ok": True,
            "image": img_b64,
            "format": "png",
            "count": len(elements),
            "elements": {
                k: {
                    "text": v.get("text", ""),
                    "bbox": v.get("bbox", []),
                    "center": v.get("center", {}),
                    "type": v.get("type", "unknown"),
                    "automation_id": v.get("automation_id", ""),
                }
                for k, v in element_map.items()
            },
            "monitor": monitor_index,
            "method": "uia" if uia_ok else "ocr",
            "elapsed_ms": elapsed_ms,
            "usage": "POST /som/click {\"number\": N} to click element N",
        })

    @app.route("/som/click", methods=["POST"])
    @require_auth
    def route_som_click():
        """
        Click the center of element N from the last /som/annotate call.
        Body: {"number": N, "button": "left"}
        """
        d = _json_body()
        number = d.get("number") or d.get("id") or d.get("n")
        if number is None:
            return jsonify(_make_error(
                "Missing element number",
                "Provide {\"number\": N} where N comes from /som/annotate",
                "Call POST /som/annotate first, then use a number from the elements map",
                "MISSING_NUMBER",
            )), 400

        try:
            number = int(number)
        except (TypeError, ValueError):
            return jsonify(_make_error(
                f"Invalid element number: {number!r}",
                "number must be an integer",
                "Use an integer key from the /som/annotate 'elements' map",
                "INVALID_NUMBER",
            )), 400

        with _SOM_STATE_LOCK:
            element_map = _load_som_state()

        if element_map is None:
            return jsonify(_make_error(
                "No SOM state — annotate first",
                "The server has no cached element positions from a recent annotate call",
                "POST /som/annotate to label the screen, then POST /som/click",
                "NO_SOM_STATE",
            )), 409

        elem = element_map.get(str(number))
        if elem is None:
            valid = sorted(int(k) for k in element_map.keys())
            sample = valid[:20]
            return jsonify(_make_error(
                f"Element {number} not found",
                f"Valid numbers: {sample}{'...' if len(valid) > 20 else ''}",
                "Check /som/annotate response — element numbers change each annotate call",
                "ELEMENT_NOT_FOUND",
            )), 404

        center = elem.get("center", {})
        bbox = elem.get("bbox", [])
        if center:
            cx = int(center.get("x", 0))
            cy = int(center.get("y", 0))
        elif len(bbox) >= 4:
            cx = int(bbox[0]) + int(bbox[2]) // 2
            cy = int(bbox[1]) + int(bbox[3]) // 2
        else:
            return jsonify(_make_error(
                f"Element {number} has no position data",
                f"Element: {elem}",
                "Re-run /som/annotate to refresh element positions",
                "NO_POSITION",
            )), 500

        button = d.get("button", "left")

        try:
            from routes_mouse import _mouse_action
            click_result = _mouse_action("click", cx, cy, button, True, state)
            if isinstance(click_result, tuple):
                result_payload = (click_result[0].get_json(silent=True)
                                  if hasattr(click_result[0], "get_json") else {})
                http_status = int(click_result[1]) if len(click_result) > 1 else 200
            else:
                result_payload = (click_result.get_json(silent=True)
                                  if hasattr(click_result, "get_json") else {})
                http_status = getattr(click_result, "status_code", 200)
        except Exception as exc:
            return jsonify(_make_error(
                f"Mouse click failed at ({cx}, {cy})",
                f"{type(exc).__name__}: {exc}",
                "Ensure the window is still visible and foreground",
                "CLICK_FAILED",
            )), 500

        return jsonify({
            "ok": http_status < 400,
            "number": number,
            "element": {
                "text": elem.get("text", ""),
                "type": elem.get("type", ""),
                "bbox": elem.get("bbox", []),
            },
            "clicked_at": {"x": cx, "y": cy},
            "button": button,
            "click_result": result_payload,
        }), http_status

    @app.route("/som/read", methods=["POST"])
    @require_auth
    def route_som_read():
        """
        Return detailed info about element N from the last /som/annotate call.
        Optionally refreshes UIA properties if the engine is available.
        Body: {"number": N}
        """
        d = _json_body()
        number = d.get("number") or d.get("id") or d.get("n")
        if number is None:
            return jsonify(_make_error(
                "Missing element number",
                "Provide {\"number\": N} where N comes from /som/annotate",
                "Call POST /som/annotate first, then use a number from the elements map",
                "MISSING_NUMBER",
            )), 400

        try:
            number = int(number)
        except (TypeError, ValueError):
            return jsonify(_make_error(
                f"Invalid element number: {number!r}",
                "number must be an integer",
                "Use an integer key from the /som/annotate 'elements' map",
                "INVALID_NUMBER",
            )), 400

        with _SOM_STATE_LOCK:
            element_map = _load_som_state()

        if element_map is None:
            return jsonify(_make_error(
                "No SOM state — annotate first",
                "The server has no cached element positions",
                "POST /som/annotate to label the screen, then POST /som/read",
                "NO_SOM_STATE",
            )), 409

        elem = element_map.get(str(number))
        if elem is None:
            valid = sorted(int(k) for k in element_map.keys())
            sample = valid[:20]
            return jsonify(_make_error(
                f"Element {number} not found",
                f"Valid numbers: {sample}{'...' if len(valid) > 20 else ''}",
                "Check /som/annotate response — numbers reset each annotate call",
                "ELEMENT_NOT_FOUND",
            )), 404

        # Try to refresh UIA properties for this position
        uia_properties = {}
        ue = _get_ue()
        if ue is not None:
            try:
                center = elem.get("center", {})
                px = center.get("x", 0)
                py = center.get("y", 0)
                from routes_uia import _walk_uia_nodes, _rect_payload
                snap = ue.uia_snapshot(timeout=3)
                if snap.get("success"):
                    for node in _walk_uia_nodes(snap.get("tree") or {}):
                        rect = _rect_payload(node.get("rect"))
                        if not rect:
                            continue
                        if (rect["x"] <= px <= rect["x"] + rect["width"] and
                                rect["y"] <= py <= rect["y"] + rect["height"]):
                            uia_properties = {
                                "name": node.get("name", ""),
                                "control_type": node.get("control_type", ""),
                                "automation_id": node.get("automation_id", ""),
                                "class_name": node.get("class_name", ""),
                                "is_enabled": node.get("is_enabled"),
                                "is_keyboard_focusable": node.get("is_keyboard_focusable"),
                                "patterns": node.get("patterns", []),
                                "value": node.get("value", ""),
                            }
                            break
            except Exception as exc:
                _log(f"[som/read] UIA property refresh failed: {exc}")

        return jsonify({
            "ok": True,
            "number": number,
            "element": elem,
            "uia_properties": uia_properties,
        })
