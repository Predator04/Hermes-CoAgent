"""OmniParser routes for UI element detection and click-target resolution."""

import base64
import binascii
import json
import os
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

try:  # match the optional shared-helpers pattern used by routes_agent.py
    from shared import _console, _wrap_registered_blueprint_routes
except Exception:  # pragma: no cover - standalone import outside the app
    def _console(message):
        print(message)

    def _wrap_registered_blueprint_routes(app, blueprint_name, require_auth):
        pass


bp = Blueprint("omniparser", __name__)

DEFAULT_OMNI_PARSER_URL = "http://127.0.0.1:8001/parse"
OMNI_PARSER_TIMEOUT_SECONDS = 30
MAX_IMAGE_BASE64_CHARS = 32 * 1024 * 1024

_UNREACHABLE = {"error": "omniparser endpoint not reachable", "ok": False}

_BOX_KEYS = ("box", "bbox", "bBox", "bounding_box")
_LABEL_KEYS = ("label", "content", "text", "caption")
_CONFIDENCE_KEYS = ("confidence", "score", "prob")


def _omni_parser_url():
    url = os.environ.get("OMNI_PARSER_URL", "").strip()
    return url or DEFAULT_OMNI_PARSER_URL


def _json_payload():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _validate_image_base64(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("image_base64 is required")
    if len(value) > MAX_IMAGE_BASE64_CHARS:
        raise ValueError("image_base64 exceeds the maximum allowed size")
    stripped = value.strip()
    if stripped.startswith("data:"):
        stripped = stripped.split(",", 1)[-1]
    try:
        base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 is not valid base64") from exc
    return stripped


def _normalize_box(value):
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if isinstance(value[0], (list, tuple)):  # nested [[x1,y1],[x2,y2]] form
        flat = [coordinate for point in value for coordinate in point]
    else:
        flat = list(value)
    if len(flat) < 4:
        return None
    box = []
    for coordinate in flat[:4]:
        try:
            box.append(float(coordinate))
        except (TypeError, ValueError):
            return None
    return box


def _normalize_element(raw):
    if not isinstance(raw, dict):
        return None
    box = None
    for key in _BOX_KEYS:
        box = _normalize_box(raw.get(key))
        if box:
            break
    if not box:
        return None
    label = ""
    for key in _LABEL_KEYS:
        if isinstance(raw.get(key), str) and raw.get(key).strip():
            label = raw.get(key).strip()
            break
    confidence = 1.0
    for key in _CONFIDENCE_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            try:
                confidence = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                confidence = 1.0
            break
    return {"label": label, "box": box, "confidence": confidence}


def _parse_omniparser_response(payload):
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = None
        for key in ("annotations", "elements", "results", "parsed", "boxes", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if candidates is None:
            candidates = []
    else:
        candidates = []
    elements = []
    for raw in candidates:
        element = _normalize_element(raw)
        if element:
            elements.append(element)
    return elements


def _request_omniparser(image_base64):
    """POST the image to the configured OmniParser endpoint.

    Returns (elements, error_response). Exactly one side is populated.
    """
    body = json.dumps({"image": image_base64}).encode("utf-8")
    req = urllib.request.Request(
        _omni_parser_url(),
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OMNI_PARSER_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, _UNREACHABLE
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            return None, _UNREACHABLE
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return None, _error(f"omniparser returned HTTP {exc.code}: {detail}", 502)
    try:
        payload = json.loads(text) if text else []
    except ValueError:
        return None, _error("omniparser returned a non-JSON response", 502)
    return _parse_omniparser_response(payload), None


@bp.route("/omniparser/elements", methods=["POST"])
def route_omniparser_elements():
    data = _json_payload()
    try:
        image_base64 = _validate_image_base64(data.get("image_base64"))
    except ValueError as exc:
        return _error(str(exc), 400)
    elements, error = _request_omniparser(image_base64)
    if error is not None:
        return error
    return jsonify(elements)


@bp.route("/omniparser/click", methods=["POST"])
def route_omniparser_click():
    data = _json_payload()
    try:
        image_base64 = _validate_image_base64(data.get("image_base64"))
    except ValueError as exc:
        return _error(str(exc), 400)
    target = data.get("target")
    if not isinstance(target, str) or not target.strip():
        return _error("target is required", 400)
    target_lower = target.strip().lower()
    elements, error = _request_omniparser(image_base64)
    if error is not None:
        return error
    for element in elements:
        if target_lower in element["label"].lower():
            x1, y1, x2, y2 = element["box"]
            return jsonify({
                "x": round((x1 + x2) / 2, 2),
                "y": round((y1 + y2) / 2, 2),
                "label": element["label"],
                "ok": True,
            })
    return jsonify({"error": f"no element matching target: {target}", "ok": False}), 404


def register_routes(app, state, require_auth):
    app.register_blueprint(bp)
    _wrap_registered_blueprint_routes(app, bp.name, require_auth)
