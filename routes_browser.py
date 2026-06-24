"""Patchright/Playwright browser control routes."""

import base64
import threading
from pathlib import Path

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import _sanitize_path


browser_bp = Blueprint("browser", __name__)

_BROWSER_LOCK = threading.RLock()
_PW = None
_BROWSER = None
_CONTEXT = None
_PAGE = None


def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _playwright_missing():
    return _error(
        "patchright or playwright not installed. Install with: "
        "pip install patchright-python playwright && python -m playwright install chromium",
        501,
        package="patchright-python",
    )


def _load_playwright():
    try:
        from patchright.sync_api import Error as PlaywrightError
        from patchright.sync_api import sync_playwright

        return sync_playwright, PlaywrightError, None
    except ImportError:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright

            return sync_playwright, PlaywrightError, None
        except ImportError:
            return None, Exception, _playwright_missing()


def _ensure_browser(new_page=False):
    global _PW, _BROWSER, _CONTEXT, _PAGE
    sync_playwright, _playwright_error, missing = _load_playwright()
    if missing:
        return None, missing
    try:
        if _PW is None:
            _PW = sync_playwright().start()
        if _BROWSER is None or not _BROWSER.is_connected():
            _BROWSER = _PW.chromium.launch(headless=False)
            _CONTEXT = _BROWSER.new_context()
            _PAGE = None
        if _CONTEXT is None:
            _CONTEXT = _BROWSER.new_context()
        if new_page or _PAGE is None or _PAGE.is_closed():
            _PAGE = _CONTEXT.new_page()
        return _PAGE, None
    except Exception as e:
        return None, _error(str(e), 500, type=type(e).__name__)


def _current_status():
    with _BROWSER_LOCK:
        try:
            open_browser = bool(_BROWSER and _BROWSER.is_connected())
            pages = list(_CONTEXT.pages) if _CONTEXT else []
            active_page = _PAGE if _PAGE and not _PAGE.is_closed() else (pages[-1] if pages else None)
            return {
                "open": open_browser,
                "pages": len(pages),
                "current_url": active_page.url if active_page else None,
            }
        except Exception as e:
            return {"open": False, "pages": 0, "current_url": None, "error": str(e)}


@browser_bp.route("/browser", methods=["GET"])
def route_browser_index():
    installed = _load_playwright()[2] is None
    return jsonify({
        "installed": installed,
        "endpoints": [
            {"path": "/browser", "method": "GET", "desc": "List browser endpoints"},
            {"path": "/browser/navigate", "method": "POST", "desc": "Navigate to a URL"},
            {"path": "/browser/click", "method": "POST", "desc": "Click by selector or text"},
            {"path": "/browser/fill", "method": "POST", "desc": "Fill an input"},
            {"path": "/browser/extract", "method": "POST", "desc": "Extract page text"},
            {"path": "/browser/screenshot", "method": "POST", "desc": "Capture browser screenshot"},
            {"path": "/browser/evaluate", "method": "POST", "desc": "Run JavaScript"},
            {"path": "/browser/cookies", "method": "POST", "desc": "Get or set cookies"},
            {"path": "/browser/close", "method": "POST", "desc": "Close browser"},
            {"path": "/browser/status", "method": "GET", "desc": "Browser status"},
        ],
    })


@browser_bp.route("/browser/status", methods=["GET"])
def route_browser_status():
    return jsonify(_current_status())


@browser_bp.route("/browser/navigate", methods=["POST"])
def route_browser_navigate():
    data = _json_payload()
    url = data.get("url")
    if not isinstance(url, str) or not url:
        return _error("url is required")
    new_page = _as_bool(data.get("new_page"), True)
    with _BROWSER_LOCK:
        page, error = _ensure_browser(new_page=new_page)
        if error:
            return error
        try:
            page.goto(url, wait_until=data.get("wait_until", "load"), timeout=int(data.get("timeout", 30000)))
            return jsonify({"status": "navigated", "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/click", methods=["POST"])
def route_browser_click():
    data = _json_payload()
    selector = data.get("selector")
    text = data.get("text")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if isinstance(selector, str) and selector:
                page.click(selector, timeout=int(data.get("timeout", 10000)))
                target = {"selector": selector}
            elif isinstance(text, str) and text:
                page.get_by_text(text).click(timeout=int(data.get("timeout", 10000)))
                target = {"text": text}
            else:
                return _error("selector or text is required")
            return jsonify({"status": "clicked", "url": page.url, **target})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/fill", methods=["POST"])
def route_browser_fill():
    data = _json_payload()
    selector = data.get("selector")
    value = data.get("value")
    if not isinstance(selector, str) or not selector:
        return _error("selector is required")
    if value is None:
        return _error("value is required")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.fill(selector, str(value), timeout=int(data.get("timeout", 10000)))
            return jsonify({"status": "filled", "selector": selector, "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/extract", methods=["POST"])
def route_browser_extract():
    data = _json_payload()
    selector = data.get("selector")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if isinstance(selector, str) and selector:
                text = page.locator(selector).inner_text(timeout=int(data.get("timeout", 10000)))
            else:
                text = page.inner_text("body", timeout=int(data.get("timeout", 10000)))
            return jsonify({"text": text, "selector": selector, "url": page.url, "chars": len(text)})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/screenshot", methods=["POST"])
def route_browser_screenshot():
    data = _json_payload()
    full_page = _as_bool(data.get("full_page"), True)
    path = data.get("path")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if isinstance(path, str) and path:
                safe_path = Path(_sanitize_path(path))
                safe_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(safe_path), full_page=full_page)
                return jsonify({"status": "saved", "path": str(safe_path), "url": page.url})
            data_bytes = page.screenshot(full_page=full_page)
            return jsonify({
                "status": "captured",
                "format": "png",
                "data": base64.b64encode(data_bytes).decode("ascii"),
                "url": page.url,
            })
        except ValueError as e:
            return _error(str(e), 403)
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/evaluate", methods=["POST"])
def route_browser_evaluate():
    data = _json_payload()
    script = data.get("script")
    if not isinstance(script, str) or not script:
        return _error("script is required")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            result = page.evaluate(script)
            try:
                return jsonify({"result": result, "url": page.url})
            except TypeError:
                return jsonify({"result": str(result), "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/cookies", methods=["POST"])
def route_browser_cookies():
    data = _json_payload()
    action = str(data.get("action", "get")).lower()
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if action == "get":
                return jsonify({"cookies": _CONTEXT.cookies(), "url": page.url})
            if action == "set":
                cookies = data.get("cookies")
                if not isinstance(cookies, list):
                    return _error("cookies must be a list")
                _CONTEXT.add_cookies(cookies)
                return jsonify({"status": "set", "count": len(cookies), "url": page.url})
            return _error("action must be get or set")
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/close", methods=["POST"])
def route_browser_close():
    global _PW, _BROWSER, _CONTEXT, _PAGE
    with _BROWSER_LOCK:
        try:
            if _CONTEXT is not None:
                _CONTEXT.close()
            if _BROWSER is not None:
                _BROWSER.close()
            if _PW is not None:
                _PW.stop()
            _PW = None
            _BROWSER = None
            _CONTEXT = None
            _PAGE = None
            return jsonify({"status": "closed"})
        except Exception as e:
            _PW = None
            _BROWSER = None
            _CONTEXT = None
            _PAGE = None
            return _error(str(e), 500, type=type(e).__name__)


def register_routes(app, state, require_auth):
    _auth_blueprint(browser_bp, require_auth)
    app.register_blueprint(browser_bp)
