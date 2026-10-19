"""
Screenshot annotation — draw numbered boxes over interactive UI elements.

AI agent / user flow:
  POST /screen/annotate
      body: {"screenshot_base64": str or null}
      - null (or omitted) → capture a fresh screenshot via the existing
        capture chain (routes_ocr._capture_raw: DXCam → MSS → Win32 → relay)
      - str → use the caller-supplied base64 PNG screenshot instead
  → {"ok": true, "image_base64": <PNG with numbered boxes>, "elements":
     [{"index": N, "label": "...", "box": [x1, y1, x2, y2]}]}

Element enumeration uses the UIA accessibility engine from routes_uia
(_get_uia_engine → uia_engine.uia_snapshot). If UIA is unavailable the
route returns {"ok": false, "error": ...}.
"""
import base64
from io import BytesIO

from flask import Blueprint, jsonify

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from routes_uia import _get_uia_engine, _walk_uia_nodes, _rect_payload
from shared import _json_body, _log

bp = Blueprint("annotate", __name__)

# Control types worth drawing a box for (same set as routes_som).
INTERACTIVE_CONTROL_TYPES = {
    "button", "edit", "checkbox", "radiobutton", "combobox",
    "listitem", "menuitem", "tabitem", "link", "hyperlink",
    "splitbutton", "togglebutton", "slider", "spinbox",
    "dataitem", "treeitem", "text",
}

_MAX_ELEMENTS = 200

_BOX_COLORS = [
    (220, 53, 69),   # red
    (40, 167, 69),   # green
    (0, 123, 255),   # blue
    (255, 140, 0),   # orange
    (111, 66, 193),  # purple
    (23, 162, 184),  # cyan
    (255, 193, 7),   # yellow
]


def _error(error, detail="", code="ERROR", status=500):
    payload = {"ok": False, "error": error}
    if detail:
        payload["detail"] = detail
    if code:
        payload["code"] = code
    return jsonify(payload), status


def _load_fonts():
    """Return (number_font, label_font); defaults if truetype unavailable."""
    try:
        number_font = ImageFont.truetype("arialbd.ttf", 12)
    except Exception:
        try:
            number_font = ImageFont.load_default()
        except Exception:
            number_font = None
    return number_font


def _collect_elements(ue):
    """Enumerate interactive UIA elements as dicts with absolute [x1,y1,x2,y2] boxes."""
    elements = []
    try:
        snap = ue.uia_snapshot(timeout=5)
    except Exception as exc:
        _log(f"[annotate] UIA snapshot failed: {exc}")
        return elements
    if not snap.get("success"):
        _log(f"[annotate] UIA snapshot unsuccessful: {snap.get('error', 'unknown')}")
        return elements

    seen = set()
    for node in _walk_uia_nodes(snap.get("tree") or {}, max_depth=10):
        rect = _rect_payload(node.get("rect"))
        if not rect:
            continue
        ctrl = str(node.get("control_type") or "").lower().strip()
        if "." in ctrl:  # strip "ControlType." prefix some engines emit
            ctrl = ctrl.rsplit(".", 1)[-1]
        if ctrl not in INTERACTIVE_CONTROL_TYPES:
            continue
        label = str(node.get("name") or "").strip() or ctrl
        x1, y1 = rect["x"], rect["y"]
        x2, y2 = x1 + rect["width"], y1 + rect["height"]
        key = (label, x1, y1, x2, y2)
        if key in seen:
            continue
        seen.add(key)
        elements.append({
            "label": label[:200],
            "box": [x1, y1, x2, y2],
            "control_type": ctrl,
            "automation_id": node.get("automation_id", ""),
            "class_name": node.get("class_name", ""),
            "enabled": bool(node.get("is_enabled", True)),
        })
        if len(elements) >= _MAX_ELEMENTS:
            break
    return elements


def _annotate_image(pil_img, elements):
    """Draw a colored numbered box + badge label per element on a copy of the image."""
    img = pil_img.copy()
    draw = ImageDraw.Draw(img)
    font = _load_fonts()

    for i, elem in enumerate(elements, 1):
        x1, y1, x2, y2 = (int(v) for v in elem["box"])
        if x2 <= x1 or y2 <= y1:
            continue
        color = _BOX_COLORS[(i - 1) % len(_BOX_COLORS)]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        # Number badge at top-left corner
        text = str(i)
        badge_w, badge_h = 24, 18
        bx, by = max(0, x1), max(0, y1 - badge_h)
        draw.rectangle([bx, by, bx + badge_w, by + badge_h], fill=color)
        if font is not None:
            draw.text((bx + 4, by + 2), text, fill="white", font=font)
        else:
            draw.text((bx + 4, by + 2), text, fill="white")
    return img


@bp.route("/screen/annotate", methods=["POST"])
def route_screen_annotate():
    """Screenshot + numbered boxes over interactive elements."""
    if not HAS_PIL:
        return _error("PIL not available",
                      "Pillow is required to draw annotation boxes",
                      "PIL_MISSING")

    d = _json_body() or {}
    screenshot_base64 = d.get("screenshot_base64")

    # 1. Screenshot: caller-supplied or fresh capture through the existing chain.
    raw = None
    if screenshot_base64:
        try:
            raw = base64.b64decode(screenshot_base64, validate=False)
        except Exception as exc:
            return _error("Invalid screenshot_base64",
                          f"{type(exc).__name__}: {exc}", "BAD_BASE64", 400)
        if not raw:
            return _error("Empty screenshot_base64", "Decoded to 0 bytes",
                          "EMPTY_SCREENSHOT", 400)
    else:
        try:
            from routes_ocr import _capture_raw
            raw = _capture_raw(force=True)
        except Exception as exc:
            return _error("Screenshot failed", f"{type(exc).__name__}: {exc}",
                          "SCREENSHOT_FAILED")
        if not raw:
            return _error("Screenshot failed", "Capture chain returned empty bytes",
                          "EMPTY_SCREENSHOT")

    # 2. UIA element enumeration (the repo's UIA engine via routes_uia).
    try:
        ue = _get_uia_engine()
    except Exception as exc:
        return _error("UIA unavailable", f"{type(exc).__name__}: {exc}",
                      "UIA_UNAVAILABLE")
    if ue is None:
        return _error("UIA unavailable",
                      "UIA engine could not be loaded (Windows UIA backend missing)",
                      "UIA_UNAVAILABLE")

    elements = _collect_elements(ue)
    if not elements:
        return _error("No interactive elements found",
                      "UIA snapshot succeeded but yielded no matching elements",
                      "NO_ELEMENTS", 404)

    # 3. Draw and encode.
    try:
        pil_img = Image.open(BytesIO(raw)).convert("RGB")
        annotated = _annotate_image(pil_img, elements)
        buf = BytesIO()
        annotated.save(buf, format="PNG")
        image_base64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        return _error("Annotation failed", f"{type(exc).__name__}: {exc}",
                      "ANNOTATION_FAILED")

    return jsonify({
        "ok": True,
        "image_base64": image_base64,
        "format": "png",
        "count": len(elements),
        "elements": [
            {"index": i, "label": e["label"], "box": e["box"]}
            for i, e in enumerate(elements, 1)
        ],
    })


def register_routes(app, state, require_auth):
    """Register the blueprint with the CoAgent Flask app (repo convention)."""
    app.register_blueprint(bp)
