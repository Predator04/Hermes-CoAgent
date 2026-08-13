"""Undetectable browser launch routes backed by patchright when available.

Each session runs on a dedicated per-session worker thread so that every
Playwright operation (create -> navigate -> close) happens on the *same*
thread. Playwright's sync API binds every object to the event loop of its
creating thread; closing objects from a different thread raises greenlet/loop
errors and leaks the Chromium process + node driver (issue #55).
"""

import queue
import random
import threading
import time
import uuid

from flask import Blueprint, jsonify

from shared import _json_body, _wrap_registered_blueprint_routes


browser_automation_bp = Blueprint("browser_automation", __name__)

_SESSIONS = {}
_SESSIONS_LOCK = threading.RLock()

# Seconds to wait for a session's worker thread to acknowledge a close before
# giving up. Playwright close() should be near-instant; 30s is generous.
_CLOSE_TIMEOUT = 30.0

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


class _SessionWorker(threading.Thread):
    """Owns a single Playwright sync session on its own dedicated thread.

    Every Playwright object (playwright/browser/context/page) is created, used,
    and closed on this thread, so the sync API never observes cross-thread
    access. The HTTP route marshals commands to the worker through queues and
    blocks for results, preserving the request/response shape.
    """

    def __init__(self, browser_id, sync_playwright, browser_error, engine,
                 config, stealth_script):
        super().__init__(daemon=True, name=f"pw-undetectable-{browser_id[:8]}")
        self.browser_id = browser_id
        self._sync_playwright = sync_playwright
        self._browser_error = browser_error
        self._engine = engine
        self._config = config
        self._stealth_script = stealth_script
        self._cmd_queue = queue.Queue()
        self._result_queue = queue.Queue()
        self.info = None

    # -- lifecycle (runs on the worker thread) -------------------------------

    def run(self):
        pw = browser = context = page = None
        try:
            pw = self._sync_playwright().start()
            browser = pw.chromium.launch(
                headless=self._config["headless"],
                args=self._config["launch_args"],
            )
            context = browser.new_context(
                viewport=self._config["viewport"],
                user_agent=self._config["user_agent"],
                locale=self._config["locale"],
                extra_http_headers={"Accept-Language": self._config["accept_language"]},
                color_scheme=self._config["color_scheme"],
                timezone_id=self._config["timezone_id"],
            )
            context.add_init_script(self._stealth_script)
            page = context.new_page()

            warning = None
            try:
                page.goto(
                    self._config["url"],
                    wait_until=self._config["wait_until"],
                    timeout=self._config["timeout_ms"],
                )
            except self._browser_error as exc:
                warning = f"{type(exc).__name__}: {exc}"
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""

            self.info = {
                "engine": self._engine,
                "status": "opened",
                "url": page.url,
                "title": title,
                "headless": self._config["headless"],
                "viewport": self._config["viewport"],
                "user_agent": self._config["user_agent"],
                "accept_language": self._config["accept_language"],
                "created_at": time.time(),
            }
            # Signal the HTTP handler that the session is ready.
            self._result_queue.put(("ready", warning))
        except Exception as exc:
            self._cleanup(pw, browser, context)
            self._result_queue.put(("error", f"{type(exc).__name__}: {exc}"))
            return

        # Hold the session open on this thread until told to close.
        self._cmd_queue.get()

        errors = self._cleanup(pw, browser, context)
        if errors:
            self._result_queue.put(("closed", {
                "status": "closed_with_errors",
                "browser_id": self.browser_id,
                "errors": errors,
            }))
        else:
            self._result_queue.put(("closed", {
                "status": "closed",
                "browser_id": self.browser_id,
            }))

    @staticmethod
    def _cleanup(pw, browser, context):
        errors = []
        for key, obj in (("context", context), ("browser", browser)):
            try:
                if obj is not None:
                    obj.close()
            except Exception as exc:
                errors.append(f"{key}: {type(exc).__name__}: {exc}")
        try:
            if pw is not None:
                pw.stop()
        except Exception as exc:
            errors.append(f"playwright: {type(exc).__name__}: {exc}")
        return errors

    # -- marshaling API (called from the HTTP handler thread) ----------------

    def wait_ready(self, timeout):
        """Block until the worker signals ready/error. Returns (status, payload)."""
        try:
            return self._result_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("browser session failed to become ready")

    def request_close(self, timeout=_CLOSE_TIMEOUT):
        """Signal close and block for the worker's result. Returns a status dict."""
        self._cmd_queue.put("close")
        try:
            status, payload = self._result_queue.get(timeout=timeout)
        except queue.Empty:
            return {"status": "close_timed_out", "browser_id": self.browser_id}
        return payload


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

    browser_id = uuid.uuid4().hex
    config = {
        "url": url,
        "wait_until": data.get("wait_until", "load"),
        "timeout_ms": timeout_ms,
        "viewport": viewport,
        "locale": locale,
        "accept_language": accept_language,
        "user_agent": user_agent,
        "headless": headless,
        "color_scheme": str(data.get("color_scheme") or "light"),
        "timezone_id": str(data.get("timezone_id") or "America/Los_Angeles"),
        "launch_args": launch_args,
    }

    worker = _SessionWorker(
        browser_id, sync_playwright, BrowserError, engine, config,
        _stealth_init_script(accept_language),
    )
    worker.start()

    # Give the worker the navigation timeout plus launch overhead.
    ready_timeout = (timeout_ms / 1000.0) + 60.0
    try:
        status, payload = worker.wait_ready(ready_timeout)
    except TimeoutError:
        return _error("browser session failed to start within timeout", 500,
                      browser_id=browser_id)
    if status == "error":
        return _error(payload, 500)

    with _SESSIONS_LOCK:
        _SESSIONS[browser_id] = worker

    return jsonify({
        **_session_metadata(browser_id, worker.info),
        "warning": payload,
        "stealth_options": {
            "random_viewport": True,
            "webdriver_flag_disabled": True,
            "accept_language_spoofed": True,
            "realistic_user_agent": True,
        },
    })


@browser_automation_bp.route("/browser/undetectable/list", methods=["GET"])
def route_browser_undetectable_list():
    with _SESSIONS_LOCK:
        sessions = [
            _session_metadata(browser_id, worker.info or {})
            for browser_id, worker in _SESSIONS.items()
        ]
    return jsonify({"sessions": sessions, "count": len(sessions)})


@browser_automation_bp.route("/browser/undetectable/<browser_id>/close", methods=["POST"])
def route_browser_undetectable_close(browser_id):
    with _SESSIONS_LOCK:
        worker = _SESSIONS.pop(browser_id, None)
    if worker is None:
        return _error("browser session not found", 404, browser_id=browser_id)
    return jsonify(worker.request_close())


def register_routes(app, state, require_auth):
    app.register_blueprint(browser_automation_bp)
    _wrap_registered_blueprint_routes(app, browser_automation_bp.name, require_auth)
    state.browser_automation = {"undetectable_sessions": _SESSIONS}
