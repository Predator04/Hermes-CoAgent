"""Undetectable browser launch routes backed by patchright when available."""

import random
import threading
import time
import uuid

from flask import Blueprint, jsonify

from shared import _json_body, _wrap_registered_blueprint_routes


browser_automation_bp = Blueprint("browser_automation", __name__)

_SESSIONS = {}
_SESSIONS_LOCK = threading.RLock()

_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
]

_LANGUAGES = [
    ("en-US", "en-US,en;q=0.9"),
    ("en-GB", "en-GB,en-US;q=0.9,en;q=0.8"),
    ("en-CA", "en-CA,en-US;q=0.9,en;q=0.8"),
]


def _load_browser_api():
    try:
        from patchright.sync_api import Error as BrowserError
        from patchright.sync_api import sync_playwright

        return sync_playwright, BrowserError, "patchright", None
    except ImportError:
        try:
            from playwright.sync_api import Error as BrowserError
            from playwright.sync_api import sync_playwright

            return sync_playwright, BrowserError, "playwright", None
        except ImportError:
            return None, Exception, None, (
                "patchright or playwright not installed. Install with: "
                "pip install patchright-python playwright && python -m playwright install chromium"
            )


def _validate_url(url):
    """Validate URL: allow only http/https, block private/localhost IPs, allow about:blank."""
    if url == "about:blank":
        return None
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Unsupported URL scheme: {parsed.scheme or 'none'}"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "URL must include a hostname"
    blocked = {
        "localhost", "127.0.0.1", "0.0.0.0",
        "169.254.169.254",  # AWS metadata
        "metadata.google.internal",  # GCP metadata
    }
    if hostname in blocked:
        return f"Access to {hostname} is blocked"
    # Block private IP ranges
    import ipaddress
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"Access to private IP {hostname} is blocked"
    except ValueError:
        pass  # Not an IP address, allow (DNS will resolve later)
    return None


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


def _random_viewport(data):
    width = data.get("width")
    height = data.get("height")
    if width is None:
        width = random.randint(1180, 1640)
    if height is None:
        height = random.randint(720, 1080)
    return {
        "width": _clamp_int(width, 1366, 800, 3840),
        "height": _clamp_int(height, 900, 600, 2160),
    }


def _stealth_init_script(locale):
    languages = [part.split(";")[0] for part in locale.split(",") if part.strip()]
    return f"""
Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
Object.defineProperty(navigator, 'languages', {{ get: () => {languages!r} }});
Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4, 5] }});
window.chrome = window.chrome || {{ runtime: {{}} }};
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {{
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({{ state: Notification.permission }})
      : originalQuery(parameters)
  );
}}
"""


def _session_metadata(browser_id, info):
    return {
        "browser_id": browser_id,
        "engine": info.get("engine"),
        "status": info.get("status"),
        "url": info.get("url"),
        "title": info.get("title"),
        "headless": info.get("headless"),
        "viewport": info.get("viewport"),
        "user_agent": info.get("user_agent"),
        "accept_language": info.get("accept_language"),
        "created_at": info.get("created_at"),
    }


def _close_session(browser_id):
    with _SESSIONS_LOCK:
        info = _SESSIONS.pop(browser_id, None)
    if not info:
        raise KeyError("browser session not found")
    errors = []
    for key in ("context", "browser"):
        try:
            obj = info.get(key)
            if obj is not None:
                obj.close()
        except Exception as exc:
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
    try:
        pw = info.get("playwright")
        if pw is not None:
            pw.stop()
    except Exception as exc:
        errors.append(f"playwright: {type(exc).__name__}: {exc}")
    if errors:
        return {"status": "closed_with_errors", "browser_id": browser_id, "errors": errors}
    return {"status": "closed", "browser_id": browser_id}


@browser_automation_bp.route("/browser/undetectable", methods=["POST"])
def route_browser_undetectable():
    data = _json_body()
    sync_playwright, BrowserError, engine, missing = _load_browser_api()
    if missing:
        return _error(missing, 501, package="patchright-python")

    url = data.get("url") or "about:blank"
    if not isinstance(url, str) or not url:
        return _error("url must be a string")
    url_err = _validate_url(url)
    if url_err:
        return _error(url_err, 400)

    viewport = _random_viewport(data)
    locale, accept_language = random.choice(_LANGUAGES)
    locale = str(data.get("locale") or locale)
    accept_language = str(data.get("accept_language") or accept_language)
    user_agent = str(data.get("user_agent") or random.choice(_USER_AGENTS))
    headless = _as_bool(data.get("headless"), False)
    timeout_ms = _clamp_int(data.get("timeout"), 30000, 1000, 180000)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        launch_args.extend([
            "--window-position=0,0",
            f"--window-size={viewport['width']},{viewport['height']}",
        ])

    pw = browser = context = page = None
    browser_id = uuid.uuid4().hex
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless, args=launch_args)
        context = browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale=locale,
            extra_http_headers={"Accept-Language": accept_language},
            color_scheme=str(data.get("color_scheme") or "light"),
            timezone_id=str(data.get("timezone_id") or "America/Los_Angeles"),
        )
        context.add_init_script(_stealth_init_script(accept_language))
        page = context.new_page()
        warning = None
        try:
            page.goto(url, wait_until=data.get("wait_until", "load"), timeout=timeout_ms)
        except BrowserError as exc:
            warning = f"{type(exc).__name__}: {exc}"
        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""

        info = {
            "playwright": pw,
            "browser": browser,
            "context": context,
            "page": page,
            "engine": engine,
            "status": "opened",
            "url": page.url,
            "title": title,
            "headless": headless,
            "viewport": viewport,
            "user_agent": user_agent,
            "accept_language": accept_language,
            "created_at": time.time(),
        }
        with _SESSIONS_LOCK:
            _SESSIONS[browser_id] = info
        return jsonify({
            **_session_metadata(browser_id, info),
            "warning": warning,
            "stealth_options": {
                "random_viewport": True,
                "webdriver_flag_disabled": True,
                "accept_language_spoofed": True,
                "realistic_user_agent": True,
            },
        })
    except Exception as exc:
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
        return _error(f"{type(exc).__name__}: {exc}", 500)


@browser_automation_bp.route("/browser/undetectable/list", methods=["GET"])
def route_browser_undetectable_list():
    with _SESSIONS_LOCK:
        sessions = [_session_metadata(browser_id, info) for browser_id, info in _SESSIONS.items()]
    return jsonify({"sessions": sessions, "count": len(sessions)})


@browser_automation_bp.route("/browser/undetectable/<browser_id>/close", methods=["POST"])
def route_browser_undetectable_close(browser_id):
    try:
        return jsonify(_close_session(browser_id))
    except KeyError as exc:
        return _error(str(exc), 404, browser_id=browser_id)


def register_routes(app, state, require_auth):
    app.register_blueprint(browser_automation_bp)
    _wrap_registered_blueprint_routes(app, browser_automation_bp.name, require_auth)
    state.browser_automation = {"undetectable_sessions": _SESSIONS}
