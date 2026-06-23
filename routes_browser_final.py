"""Thread-owned Playwright browser automation routes."""

import json
import queue
import threading
import time
import uuid

from flask import Blueprint, Response, jsonify

from shared import _json_body


browser_v2_bp = Blueprint("browser_v2", __name__)

_BROWSERS = {}
_BROWSERS_LOCK = threading.RLock()


def _load_playwright():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
        return sync_playwright, PlaywrightError, None
    except ImportError:
        return None, Exception, (
            "Playwright not installed. Install with: "
            "pip install playwright && python -m playwright install chromium"
        )


def _error(message, status=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


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


def _clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_json_value(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _metadata(browser_id):
    with _BROWSERS_LOCK:
        info = _BROWSERS.get(browser_id)
        if not info:
            return None
        return {
            "browser_id": browser_id,
            "status": info.get("status"),
            "url": info.get("url"),
            "title": info.get("title"),
            "created_at": info.get("created_at"),
            "headless": info.get("headless"),
            "width": info.get("width"),
            "height": info.get("height"),
        }


def _set_metadata(browser_id, **updates):
    with _BROWSERS_LOCK:
        info = _BROWSERS.get(browser_id)
        if info:
            info.update(updates)


def _command(browser_id, name, payload=None, timeout=60):
    with _BROWSERS_LOCK:
        info = _BROWSERS.get(browser_id)
        if not info or info.get("status") == "closed":
            raise KeyError("browser not found")
        command_queue = info["queue"]
    response_queue = queue.Queue(maxsize=1)
    command_queue.put({"name": name, "payload": payload or {}, "response": response_queue})
    try:
        response = response_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"browser command timed out: {name}") from exc
    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "browser command failed")
    return response.get("result")


def _click_target(page, payload):
    selector = payload.get("selector")
    text = payload.get("text")
    timeout = _clamp_int(payload.get("timeout"), 10000, 100, 120000)
    if isinstance(selector, str) and selector:
        page.click(selector, timeout=timeout)
        return {"selector": selector}
    if isinstance(text, str) and text:
        locator = page.get_by_text(text, exact=_as_bool(payload.get("exact"), False))
        locator.click(timeout=timeout)
        return {"text": text}
    raise ValueError("selector or text is required")


def _type_target(page, payload):
    selector = payload.get("selector")
    text = payload.get("text")
    if text is None:
        raise ValueError("text is required")
    timeout = _clamp_int(payload.get("timeout"), 10000, 100, 120000)
    if isinstance(selector, str) and selector:
        if _as_bool(payload.get("clear"), True):
            page.fill(selector, str(text), timeout=timeout)
        else:
            page.click(selector, timeout=timeout)
            page.keyboard.type(str(text), delay=_clamp_int(payload.get("delay"), 0, 0, 1000))
    else:
        page.keyboard.type(str(text), delay=_clamp_int(payload.get("delay"), 0, 0, 1000))
    if _as_bool(payload.get("enter"), False):
        page.keyboard.press("Enter")
    return {"selector": selector, "chars": len(str(text))}


def _browser_worker(browser_id, options, ready_queue):
    sync_playwright, PlaywrightError, missing = _load_playwright()
    if missing:
        ready_queue.put({"ok": False, "error": missing})
        return

    pw = browser = context = page = None
    command_queue = options["queue"]
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=options["headless"])
        context = browser.new_context(viewport={"width": options["width"], "height": options["height"]})
        page = context.new_page()
        warning = None
        if options["url"]:
            try:
                page.goto(options["url"], wait_until="load", timeout=options["timeout_ms"])
            except Exception as exc:
                warning = f"{type(exc).__name__}: {exc}"
        title = page.title()
        _set_metadata(browser_id, status="opened", url=page.url, title=title, warning=warning)
        ready_queue.put({"ok": True, "result": {"url": page.url, "title": title, "warning": warning}})

        while True:
            item = command_queue.get()
            response_queue = item["response"]
            name = item["name"]
            payload = item.get("payload") or {}
            try:
                if name == "navigate":
                    url = payload.get("url")
                    if not isinstance(url, str) or not url:
                        raise ValueError("url is required")
                    page.goto(
                        url,
                        wait_until=payload.get("wait_until", "load"),
                        timeout=_clamp_int(payload.get("timeout"), 30000, 1000, 180000),
                    )
                    result = {"status": "navigated", "url": page.url, "title": page.title()}
                    _set_metadata(browser_id, url=page.url, title=result["title"])
                    response_queue.put({"ok": True, "result": result})
                elif name == "screenshot":
                    image = page.screenshot(full_page=_as_bool(payload.get("full_page"), True), type="png")
                    response_queue.put({"ok": True, "result": image})
                elif name == "click":
                    target = _click_target(page, payload)
                    result = {"status": "clicked", "url": page.url, **target}
                    response_queue.put({"ok": True, "result": result})
                elif name == "type":
                    detail = _type_target(page, payload)
                    result = {"status": "typed", "url": page.url, **detail}
                    response_queue.put({"ok": True, "result": result})
                elif name == "extract":
                    selector = payload.get("selector")
                    timeout = _clamp_int(payload.get("timeout"), 10000, 100, 120000)
                    if isinstance(selector, str) and selector:
                        text = page.locator(selector).inner_text(timeout=timeout)
                    else:
                        text = page.inner_text("body", timeout=timeout)
                    result = {"text": text, "title": page.title(), "url": page.url, "selector": selector}
                    response_queue.put({"ok": True, "result": result})
                elif name == "evaluate":
                    script = payload.get("script")
                    if not isinstance(script, str) or not script:
                        raise ValueError("script is required")
                    result = page.evaluate(script)
                    response_queue.put({"ok": True, "result": {"result": _safe_json_value(result), "url": page.url}})
                elif name == "close":
                    response_queue.put({"ok": True, "result": {"status": "closed", "browser_id": browser_id}})
                    break
                else:
                    raise ValueError(f"unknown browser command: {name}")
            except PlaywrightError as exc:
                response_queue.put({"ok": False, "error": f"PlaywrightError: {exc}"})
            except Exception as exc:
                response_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        ready_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        for obj in (context, browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass
        with _BROWSERS_LOCK:
            info = _BROWSERS.get(browser_id)
            if info:
                info["status"] = "closed"
                info["closed_at"] = time.time()


@browser_v2_bp.route("/browser/open", methods=["POST"])
def route_browser_open():
    sync_playwright, _playwright_error, missing = _load_playwright()
    if missing:
        return _error(missing, 501, package="playwright")
    data = _json_body()
    browser_id = uuid.uuid4().hex
    command_queue = queue.Queue()
    options = {
        "url": data.get("url") or "about:blank",
        "headless": _as_bool(data.get("headless"), False),
        "width": _clamp_int(data.get("width"), 1280, 320, 7680),
        "height": _clamp_int(data.get("height"), 720, 240, 4320),
        "timeout_ms": _clamp_int(data.get("timeout"), 30000, 1000, 180000),
        "queue": command_queue,
    }
    ready_queue = queue.Queue(maxsize=1)
    thread = threading.Thread(
        target=_browser_worker,
        args=(browser_id, options, ready_queue),
        name=f"browser-v2-{browser_id[:8]}",
        daemon=True,
    )
    with _BROWSERS_LOCK:
        _BROWSERS[browser_id] = {
            "browser_id": browser_id,
            "status": "opening",
            "queue": command_queue,
            "thread": thread,
            "created_at": time.time(),
            "url": options["url"],
            "title": "",
            "headless": options["headless"],
            "width": options["width"],
            "height": options["height"],
        }
    thread.start()
    try:
        ready = ready_queue.get(timeout=60)
    except queue.Empty:
        with _BROWSERS_LOCK:
            _BROWSERS.pop(browser_id, None)
        return _error("browser open timed out", 504, browser_id=browser_id)
    if not ready.get("ok"):
        with _BROWSERS_LOCK:
            _BROWSERS.pop(browser_id, None)
        return _error(ready.get("error") or "failed to open browser", 500)
    result = ready.get("result") or {}
    return jsonify({
        "browser_id": browser_id,
        "status": "opened",
        "url": result.get("url"),
        "title": result.get("title"),
        "warning": result.get("warning"),
    })


@browser_v2_bp.route("/browser/navigate/<browser_id>", methods=["POST"])
def route_browser_navigate(browser_id):
    data = _json_body()
    try:
        return jsonify(_command(browser_id, "navigate", data, timeout=180))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/screenshot/<browser_id>", methods=["GET"])
def route_browser_screenshot(browser_id):
    try:
        image = _command(browser_id, "screenshot", {}, timeout=60)
        return Response(image, mimetype="image/png")
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/click/<browser_id>", methods=["POST"])
def route_browser_click(browser_id):
    try:
        return jsonify(_command(browser_id, "click", _json_body(), timeout=60))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/type/<browser_id>", methods=["POST"])
def route_browser_type(browser_id):
    try:
        return jsonify(_command(browser_id, "type", _json_body(), timeout=60))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/extract/<browser_id>", methods=["POST"])
def route_browser_extract(browser_id):
    try:
        return jsonify(_command(browser_id, "extract", _json_body(), timeout=60))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/evaluate/<browser_id>", methods=["POST"])
def route_browser_evaluate(browser_id):
    try:
        return jsonify(_command(browser_id, "evaluate", _json_body(), timeout=60))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/close/<browser_id>", methods=["POST"])
def route_browser_close(browser_id):
    try:
        result = _command(browser_id, "close", {}, timeout=30)
        return jsonify(result)
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)
    except TimeoutError as exc:
        return _error(str(exc), 504, browser_id=browser_id)
    except Exception as exc:
        return _error(str(exc), 500, browser_id=browser_id)


@browser_v2_bp.route("/browser/list", methods=["GET"])
def route_browser_list():
    with _BROWSERS_LOCK:
        browsers = [
            _metadata(browser_id)
            for browser_id, info in _BROWSERS.items()
            if info.get("status") != "closed"
        ]
    browsers = [item for item in browsers if item]
    return jsonify({"browsers": browsers, "count": len(browsers)})


def register_routes(app, state, require_auth):
    for endpoint, view_func in list(browser_v2_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        browser_v2_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(browser_v2_bp)
    state.browser_v2 = {"instances": _BROWSERS}
