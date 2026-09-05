"""Compact numbered UI wireframe — text-first, token-cheap agent grounding.

Endpoints:
  GET  /screen/wireframe        - numbered text representation of interactive
                                  elements in the foreground window
  POST /screen/wireframe/click  - click an element by its wireframe number

Produces a deterministic, numbered, text-first screen representation the agent
can use instead of shipping a full-res screenshot to a vision model: every
interactive element (button, field, checkbox, tab, ...) gets a stable number,
sorted top-to-bottom then left-to-right, so the model can say "click #42" and
CoAgent resolves the number to a screen coordinate.

Deterministic-first: when UIA is available, no screenshot is needed at all —
the wireframe is the grounding artifact and vision is only used to verify
landing. If UIA is unavailable, returns an empty wireframe with a hint so
callers can fall back to OCR/vision.

Windows-only imports are wrapped in try/except so this file imports cleanly
under a Linux syntax check.
"""

import time

from flask import jsonify, request

from shared import _json_body, _log

# Control types an agent can meaningfully act on (mirrors routes_perception).
_ACTIONABLE_TYPES = {
    "button", "edit", "checkbox", "radiobutton", "combobox", "listitem",
    "menuitem", "tabitem", "link", "hyperlink", "splitbutton", "togglebutton",
    "slider", "spinbox", "dataitem", "treeitem", "document", "text",
    "header", "headeritem", "menubar", "toolbar", "window", "pane",
    "group", "list", "table", "datagrid", "image", "custom", "menu",
}

_MAX_ELEMENTS = 200


def _bbox(rect):
    """Normalize a rect dict to [x, y, w, h] or None."""
    if not isinstance(rect, dict):
        return None
    left = rect.get("left", rect.get("x"))
    top = rect.get("top", rect.get("y"))
    width = rect.get("width")
    height = rect.get("height")
    if width is None and left is not None and rect.get("right") is not None:
        width = rect["right"] - left
    if height is None and top is not None and rect.get("bottom") is not None:
        height = rect["bottom"] - top
    if left is None or top is None or width is None or height is None:
        return None
    try:
        box = [int(left), int(top), int(width), int(height)]
    except (TypeError, ValueError):
        return None
    if box[2] <= 0 or box[3] <= 0:
        return None
    return box


def _collect_elements():
    """Walk the UIA tree and return a flat list of actionable element dicts."""
    elements = []
    try:
        from routes_uia import _get_uia_engine
        ue = _get_uia_engine()
        snap = ue.uia_snapshot()
        if not snap.get("success"):
            return elements
        tree = snap.get("tree") or {}

        def walk(node, depth=0):
            if depth > 10 or len(elements) >= _MAX_ELEMENTS:
                return
            if not isinstance(node, dict):
                return
            if node.get("visible") is False:
                return
            ctype = str(node.get("control_type") or node.get("type") or "").lower()
            name = str(node.get("name") or "").strip()
            auto_id = str(node.get("automation_id")
                          or node.get("automationId") or "").strip()
            if ctype in _ACTIONABLE_TYPES and (name or auto_id):
                elements.append({
                    "role": ctype,
                    "name": name,
                    "automation_id": auto_id,
                    "bbox": _bbox(node.get("rect") or node.get("bounding_rect")),
                    "enabled": bool(node.get("enabled", True)),
                })
            for child in node.get("children") or []:
                walk(child, depth + 1)

        walk(tree)
    except Exception as exc:
        _log(f"[wireframe] UIA walk failed: {exc}")
    return elements


def _number(elements):
    """Assign stable 1..N numbers sorted top-to-bottom then left-to-right."""
    def key(el):
        b = el["bbox"]
        if b is None:
            return (10 ** 9, 10 ** 9)
        return (b[1], b[0])

    ordered = sorted(elements, key=key)
    numbered = []
    for i, el in enumerate(ordered, 1):
        numbered.append({
            "number": i,
            "role": el["role"],
            "name": el["name"],
            "automation_id": el["automation_id"],
            "bbox": el["bbox"],
            "enabled": el["enabled"],
        })
    return numbered


def _wireframe_text(numbered):
    lines = []
    for el in numbered:
        b = el["bbox"]
        pos = f" @({b[0]},{b[1]})" if b else ""
        label = el["name"] or el["automation_id"] or "(unnamed)"
        state = "" if el["enabled"] else " [disabled]"
        lines.append(f"#{el['number']} {el['role']} \"{label}\"{state}{pos}")
    return "\n".join(lines)


def register_routes(app, state, require_auth):

    @app.route("/screen/wireframe", methods=["GET"])
    @require_auth
    def route_wireframe():
        """Numbered text-first wireframe of interactive elements."""
        elements = _number(_collect_elements())
        text = _wireframe_text(elements)
        return jsonify({
            "wireframe": text,
            "elements": elements,
            "count": len(elements),
            "token_estimate": (len(text) // 3) + 1,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @app.route("/screen/wireframe/click", methods=["POST"])
    @require_auth
    def route_wireframe_click():
        """Click an element by its wireframe number.

        Body: {"number": 42}
        """
        body = _json_body() or {}
        try:
            number = int(body.get("number"))
        except (TypeError, ValueError):
            return jsonify({"error": "number must be an integer"}), 400

        elements = _number(_collect_elements())
        if number < 1 or number > len(elements):
            return jsonify({
                "error": f"number out of range",
                "valid_range": [1, len(elements)],
            }), 404

        el = elements[number - 1]
        b = el["bbox"]
        if b is None:
            return jsonify({
                "error": "element has no bounding box",
                "number": number,
                "role": el["role"],
                "name": el["name"],
            }), 409

        cx = b[0] + b[2] // 2
        cy = b[1] + b[3] // 2
        try:
            from routes_mouse import _mouse_action
            return _mouse_action("click", cx, cy, "left", True, state)
        except Exception as exc:
            _log(f"[wireframe] click failed: {exc}")
            return jsonify({"error": f"click failed: {exc}"}), 500
