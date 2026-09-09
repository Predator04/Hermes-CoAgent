"""Camofox stealth-browser proxy routes.

Proxies to a Camoufox-based anti-detection browser server
(camofox-browser, https://github.com/jo-inc/camofox-browser) which runs as a
sidecar (Node.js, default http://localhost:9377). Gives CoAgent a
fingerprint-spoofed Firefox backend that passes most bot-detection (Google,
basic Cloudflare) where plain Playwright/Chromium gets flagged.

The camofox service is external to CoAgent (Python stays dependency-free).
Configure via environment:
  CAMOFOX_URL  (default http://localhost:9377)
  CAMOFOX_KEY  (Bearer access key; falls back to <COAGENT_DIR>/.camofox_token)
"""

import os
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, Response, jsonify, request

from shared import COAGENT_DIR, _is_private_url

camofox_bp = Blueprint("camofox", __name__)

CAMOFOX_URL = os.environ.get("CAMOFOX_URL", "http://localhost:9377").rstrip("/")
CAMOFOX_KEY = os.environ.get("CAMOFOX_KEY", "")

_DEFAULT_USER = "coagent"


def _key():
    if CAMOFOX_KEY:
        return CAMOFOX_KEY
    candidates = [
        os.path.join(COAGENT_DIR, ".camofox_token"),
        os.path.expanduser("~/.hermes/config/camofox_token.txt"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
                if value:
                    return value
        except OSError:
            continue
    return ""


def _headers():
    headers = {"Content-Type": "application/json"}
    key = _key()
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


def _call(method, path, body=None, timeout=90):
    url = CAMOFOX_URL + path
    data = None
    if body is not None:
        import json

        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "image" in ctype:
                return raw, ctype
            import json

            return json.loads(raw.decode("utf-8")), ctype
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        return {"error": "camofox HTTP %d" % exc.code, "detail": detail}, "application/json"
    except urllib.error.URLError as exc:
        return {
            "error": "camofox unreachable",
            "detail": str(getattr(exc, "reason", exc)),
            "hint": "is the camofox-browser sidecar running on %s?" % CAMOFOX_URL,
        }, "application/json"


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _uid(data):
    user = (data or {}).get("user_id") or (data or {}).get("userId")
    return str(user or _DEFAULT_USER)


def _tab_id(data):
    return (data or {}).get("tab_id") or (data or {}).get("tabId")


def _url_guard(url):
    if not isinstance(url, str) or not url.strip():
        return "url is required"
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return "url must be http or https"
    if _is_private_url(url.strip()):
        return "url resolves to a blocked private or internal address"
    return None


@camofox_bp.route("/camofox/health", methods=["GET"])
def route_camofox_health():
    result, _ctype = _call("GET", "/health", timeout=10)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/tabs", methods=["GET"])
def route_camofox_tabs():
    user_id = request.args.get("user_id", _DEFAULT_USER)
    result, _ctype = _call("GET", "/tabs?userId=%s" % urllib.parse.quote(user_id))
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/open", methods=["POST"])
def route_camofox_open():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    guard = _url_guard(url)
    if guard:
        return _error(guard, 403)
    user_id = _uid(data)
    session_key = data.get("session_key") or "coagent"
    result, _ctype = _call(
        "POST", "/tabs", {"userId": user_id, "sessionKey": session_key, "url": url.strip()}
    )
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify({"tab_id": result.get("tabId"), "url": result.get("url"), "title": result.get("title")})


@camofox_bp.route("/camofox/navigate", methods=["POST"])
def route_camofox_navigate():
    data = request.get_json(silent=True) or {}
    tab_id = _tab_id(data)
    if not tab_id:
        return _error("tab_id is required")
    user_id = _uid(data)
    payload = {"userId": user_id}
    if data.get("macro"):
        payload["macro"] = data.get("macro")
        payload["query"] = data.get("query", "")
    else:
        url = data.get("url")
        guard = _url_guard(url)
        if guard:
            return _error(guard, 403)
        payload["url"] = url.strip()
    result, _ctype = _call("POST", "/tabs/%s/navigate" % urllib.parse.quote(str(tab_id)), payload)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/snapshot", methods=["GET"])
def route_camofox_snapshot():
    tab_id = request.args.get("tab_id")
    if not tab_id:
        return _error("tab_id is required")
    user_id = request.args.get("user_id", _DEFAULT_USER)
    path = "/tabs/%s/snapshot?userId=%s" % (urllib.parse.quote(tab_id), urllib.parse.quote(user_id))
    if request.args.get("include_screenshot") in ("1", "true", "yes"):
        path += "&includeScreenshot=true"
    result, _ctype = _call("GET", path)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify({"tab_id": tab_id, "url": result.get("url"), "text": result.get("snapshot"),
                    "refs": result.get("refsCount"), "truncated": result.get("truncated")})


@camofox_bp.route("/camofox/screenshot", methods=["GET"])
def route_camofox_screenshot():
    tab_id = request.args.get("tab_id")
    if not tab_id:
        return _error("tab_id is required")
    user_id = request.args.get("user_id", _DEFAULT_USER)
    path = "/tabs/%s/screenshot?userId=%s" % (urllib.parse.quote(tab_id), urllib.parse.quote(user_id))
    raw, ctype = _call("GET", path)
    if isinstance(raw, dict) and "error" in raw:
        return jsonify(raw), 502
    return Response(raw, mimetype=ctype or "image/png")


@camofox_bp.route("/camofox/click", methods=["POST"])
def route_camofox_click():
    data = request.get_json(silent=True) or {}
    tab_id = _tab_id(data)
    if not tab_id:
        return _error("tab_id is required")
    user_id = _uid(data)
    payload = {"userId": user_id}
    if data.get("ref"):
        payload["ref"] = data["ref"]
    elif data.get("selector"):
        payload["selector"] = data["selector"]
    else:
        return _error("ref or selector is required")
    result, _ctype = _call("POST", "/tabs/%s/click" % urllib.parse.quote(str(tab_id)), payload)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/type", methods=["POST"])
def route_camofox_type():
    data = request.get_json(silent=True) or {}
    tab_id = _tab_id(data)
    if not tab_id:
        return _error("tab_id is required")
    text = data.get("text")
    if text is None:
        return _error("text is required")
    user_id = _uid(data)
    payload = {"userId": user_id, "text": str(text)}
    if data.get("ref"):
        payload["ref"] = data["ref"]
    elif data.get("selector"):
        payload["selector"] = data["selector"]
    if data.get("press_enter"):
        payload["pressEnter"] = True
    result, _ctype = _call("POST", "/tabs/%s/type" % urllib.parse.quote(str(tab_id)), payload)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/scroll", methods=["POST"])
def route_camofox_scroll():
    data = request.get_json(silent=True) or {}
    tab_id = _tab_id(data)
    if not tab_id:
        return _error("tab_id is required")
    user_id = _uid(data)
    direction = data.get("direction", "down")
    if direction not in {"up", "down", "left", "right"}:
        return _error("direction must be up/down/left/right")
    payload = {"userId": user_id, "direction": direction}
    if data.get("amount") is not None:
        payload["amount"] = int(data.get("amount"))
    result, _ctype = _call("POST", "/tabs/%s/scroll" % urllib.parse.quote(str(tab_id)), payload)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/links", methods=["GET"])
def route_camofox_links():
    tab_id = request.args.get("tab_id")
    if not tab_id:
        return _error("tab_id is required")
    user_id = request.args.get("user_id", _DEFAULT_USER)
    path = "/tabs/%s/links?userId=%s" % (urllib.parse.quote(tab_id), urllib.parse.quote(user_id))
    limit = request.args.get("limit")
    if limit:
        path += "&limit=%s" % int(limit)
    result, _ctype = _call("GET", path)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


@camofox_bp.route("/camofox/close", methods=["DELETE", "POST"])
def route_camofox_close():
    tab_id = request.args.get("tab_id") or (request.get_json(silent=True) or {}).get("tab_id")
    if not tab_id:
        return _error("tab_id is required")
    user_id = request.args.get("user_id") or (request.get_json(silent=True) or {}).get("user_id", _DEFAULT_USER)
    path = "/tabs/%s?userId=%s" % (urllib.parse.quote(str(tab_id)), urllib.parse.quote(str(user_id)))
    result, _ctype = _call("DELETE", path)
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 502
    return jsonify(result)


def register_routes(app, state, require_auth):
    app.register_blueprint(camofox_bp)
    from shared import _wrap_registered_blueprint_routes

    _wrap_registered_blueprint_routes(app, camofox_bp.name, require_auth)
    state.camofox = {"url": CAMOFOX_URL}
