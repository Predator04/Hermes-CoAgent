"""
UI-TARS vision routes: click-coordinate prediction from a screenshot.

  POST /ui_tars/locate  — Send a screenshot + target description to a
                          UI-TARS vision model (OpenAI-compatible chat API)
                          and get back a click coordinate.

The model is expected to answer with a GUI action such as
  click(start_box='(536,498)')
or a bare coordinate '(536,498)'. Coordinates are parsed and scaled to
the caller's target width/height.
"""

import base64
import json
import re
import struct
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from shared import _json_body, _log

bp = Blueprint("ui_tars", __name__)

# Defaults; can be overridden by adding a "ui_tars" entry to the model config
# dict (PROVIDER_DEFAULTS in routes_agent.py), e.g.
#   PROVIDER_DEFAULTS["ui_tars"] = {"base_url": "...", "model": "..."}
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "ui-tars"
DEFAULT_TIMEOUT = 60

GUI_AGENT_PROMPT = (
    "You are a GUI agent. You are given a screenshot of a computer screen "
    "and a target element to locate. Look at the screenshot, find the UI "
    "element matching the target, and respond with ONLY a single click "
    "action pointing at its center, in this exact format:\n"
    "click(start_box='(x,y)')\n"
    "where x and y are integer pixel coordinates in the screenshot. "
    "Do not output anything else — no explanation, no markdown."
)

# Accepts: click(start_box='(x,y)') | click(start_box="(x,y)") | bare (x,y)
_COORD_RE = re.compile(
    r"(?:start_box\s*=\s*['\"]?\(?|\()?\s*(\d+)\s*,\s*(\d+)\s*\)?",
)


def _model_config(body):
    """Resolve base_url/model/api_key from request body then model config."""
    body = body or {}
    base_url = DEFAULT_BASE_URL
    model = DEFAULT_MODEL
    api_key = ""
    try:
        from routes_agent import PROVIDER_DEFAULTS
        overrides = PROVIDER_DEFAULTS.get("ui_tars") or {}
        if isinstance(overrides, dict):
            base_url = overrides.get("base_url") or base_url
            model = overrides.get("model") or model
            api_key = overrides.get("api_key") or ""
    except Exception as exc:  # config unavailable → keep defaults
        _log(f"[ui_tars] reading model config failed: {exc}")
    # Request body wins last (per-call override)
    base_url = (body.get("base_url") or "").strip() or base_url
    model = (body.get("model") or "").strip() or model
    api_key = (body.get("api_key") or "").strip() or api_key
    try:
        timeout = int(body.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return {
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "timeout": max(1, min(timeout, 300)),
    }


def _png_dimensions(data):
    """Return (width, height) from a PNG IHDR header, or None if not PNG."""
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _parse_coordinate(raw):
    """Extract (x, y) ints from UI-TARS output. Returns None if not found."""
    if not raw:
        return None
    m = _COORD_RE.search(raw)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _detect_mime(image_b64):
    """Return 'image/png' or 'image/jpeg' from the decoded magic bytes."""
    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return "image/png"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "image/png"


def _call_ui_tars(cfg, image_b64, target):
    """POST an OpenAI-compatible chat.completions request. Returns model text."""
    mime = _detect_mime(image_b64)
    messages = [
        {
            "role": "system",
            "content": GUI_AGENT_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Target element: {target}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                },
            ],
        },
    ]
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 256,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError(f"unexpected response shape: {str(data)[:200]}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):  # some servers return content parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content or ""


@bp.route("/ui_tars/locate", methods=["POST"])
def route_ui_tars_locate():
    """
    Locate a UI element in a screenshot via the UI-TARS vision model.
    Accepts: {"image_base64": str, "target": str, "width": int, "height": int}
    Returns: {"x": int, "y": int, "raw": str} scaled to width/height.
    """
    d = _json_body()
    image_b64 = (d.get("image_base64") or "").strip()
    target = (d.get("target") or "").strip()
    width = d.get("width")
    height = d.get("height")

    if not image_b64 or not target:
        return jsonify({
            "ok": False,
            "error": "Missing required fields",
            "detail": "Provide image_base64 (PNG screenshot), target, width, height",
            "code": "MISSING_FIELDS",
        }), 400
    try:
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Invalid width/height",
            "detail": "width and height must be positive integers",
            "code": "INVALID_DIMENSIONS",
        }), 400

    cfg = _model_config(d)

    # Determine the sent image's own size so coordinates can be rescaled.
    img_w, img_h = width, height
    try:
        png_data = base64.b64decode(image_b64, validate=False)
        dims = _png_dimensions(png_data)
        if dims:
            img_w, img_h = dims
    except Exception:
        pass

    try:
        raw = _call_ui_tars(cfg, image_b64, target)
    except urllib.error.URLError as exc:
        _log(f"[ui_tars] endpoint unreachable: {exc}")
        return jsonify({
            "ok": False,
            "error": "ui_tars endpoint not reachable",
            "detail": f"{cfg['base_url']}: {exc}",
            "code": "ENDPOINT_UNREACHABLE",
        }), 502
    except Exception as exc:
        _log(f"[ui_tars] model call failed: {exc}")
        return jsonify({
            "ok": False,
            "error": f"ui_tars model call failed: {exc}",
            "code": "MODEL_CALL_FAILED",
        }), 502

    coord = _parse_coordinate(raw)
    if not coord:
        return jsonify({
            "ok": False,
            "error": "no coordinate found in model output",
            "raw": raw,
            "code": "NO_COORDINATE",
        }), 422

    x, y = coord
    if img_w and img_h:
        x = round(x * width / img_w)
        y = round(y * height / img_h)
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))

    return jsonify({"ok": True, "x": x, "y": y, "raw": raw})


def register_routes(app, state, require_auth):
    from shared import _wrap_registered_blueprint_routes
    app.register_blueprint(bp)
    _wrap_registered_blueprint_routes(app, bp.name, require_auth)
