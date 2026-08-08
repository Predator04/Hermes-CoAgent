"""Patchright/Playwright browser control routes."""

import base64
import threading
import urllib.parse
from pathlib import Path

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import _is_private_url, _sanitize_path, _wrap_registered_blueprint_routes


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


def _navigation_url_error(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "url must be an http or https URL"
    if _is_private_url(url):
        return "url resolves to a blocked private or internal address"
    return None


BRWOSER_TIMEOUT_MAX_MS = 60_000  # clamp user-supplied timeouts to 60s max


def _clamp_timeout(data, key="timeout", default=10000):
    val = data.get(key, default)
    try:
        val = int(val)
    except (TypeError, ValueError):
        return default
    return max(1, min(val, BRWOSER_TIMEOUT_MAX_MS))


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


_STEALTH_SCRIPT = r"""
// === COMPREHENSIVE ANTI-DETECTION ===
(() => {
    const noise = () => Math.random() * 0.000001;
    
    // 1. Navigator properties
    const navProps = {
        webdriver: undefined,
        plugins: {length: 5, 0: {name: 'Chrome PDF Plugin'}, 1: {name: 'Chrome PDF Viewer'}, 2: {name: 'Native Client'}, 3: {name: 'Widevine Content Decryption Module'}, 4: {name: 'Microsoft Edge PDF Viewer'}},
        mimeTypes: {length: 4},
        hardwareConcurrency: 16,
        deviceMemory: 8,
        platform: 'Win32',
        vendor: 'Google Inc.',
        vendorSub: '',
        productSub: '20030107',
        maxTouchPoints: 0,
        pdfViewerEnabled: true,
        doNotTrack: null,
        cookieEnabled: true,
        appVersion: '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        onLine: true,
    };
    for (const [key, val] of Object.entries(navProps)) {
        try {
            Object.defineProperty(navigator, key, {get: () => val, configurable: true});
        } catch(e) {}
    }
    navigator.getBattery = () => Promise.resolve({charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1});
    navigator.connection = {effectiveType: '4g', rtt: 50, downlink: 10, saveData: false};
    
    // 2. Screen
    Object.defineProperty(screen, 'colorDepth', {get: () => 24});
    Object.defineProperty(screen, 'pixelDepth', {get: () => 24});
    
    // 3. window.chrome
    window.chrome = {runtime: {id: undefined, onConnect: {addListener: () => {}}, onMessage: {addListener: () => {}}}, loadTimes: () => {}, csi: () => {}, app: {}};
    
    // 4. Permissions
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) => 
        params.name === 'notifications' ? Promise.resolve({state: 'prompt', onchange: null}) : origQuery(params);
    
    // 5. Canvas fingerprint randomization
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, ...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, 1, 1);
            imageData.data[0] = imageData.data[0] ^ Math.round(noise() * 255);
            ctx.putImageData(imageData, 0, 0);
        }
        return origToDataURL.apply(this, [type, ...args]);
    };
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(x, y, w, h) {
        const data = origGetImageData.call(this, x, y, w, h);
        for (let i = 0; i < Math.min(data.data.length, 50); i++) {
            data.data[i] = data.data[i] ^ Math.round(noise() * 2);
        }
        return data;
    };
    
    // 6. WebGL fingerprint randomization
    const origGetParameter = WebGLRenderingContext.prototype.getParameter;
    const webglNoise = (val) => typeof val === 'number' ? val + noise() : val;
    WebGLRenderingContext.prototype.getParameter = function(pname) {
        const result = origGetParameter.call(this, pname);
        if (pname === 37445) return 'Intel Inc.';  // VENDOR
        if (pname === 37446) return 'Intel(R) Iris(R) Xe Graphics';  // RENDERER
        return webglNoise(result);
    };
    try {
        WebGL2RenderingContext.prototype.getParameter = WebGLRenderingContext.prototype.getParameter;
    } catch(e) {}
    
    // 7. AudioContext fingerprint protection
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(channel) {
        const data = origGetChannelData.call(this, channel);
        for (let i = 0; i < Math.min(data.length, 10); i++) {
            data[i] += noise() * 0.000001;
        }
        return data;
    };
    
    // 8. Timezone offset stability
    Date.prototype.getTimezoneOffset = (function(orig) {
        return function() { return orig.call(this); };
    })(Date.prototype.getTimezoneOffset);
    
    // 9. iframe detection (no extra frames)
    Object.defineProperty(window, 'frameElement', {get: () => null});
    
    // 10. Override toString on overridden functions
    const origToString = Function.prototype.toString;
    const nativeFuncs = [
        'HTMLCanvasElement.prototype.toDataURL',
        'CanvasRenderingContext2D.prototype.getImageData',
        'WebGLRenderingContext.prototype.getParameter',
        'AudioBuffer.prototype.getChannelData',
    ];
})();
"""

_STEALTH_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1680, "height": 1050},
    {"width": 1600, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
]
_STEALTH_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]

_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-component-extensions-with-background-pages",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "--safebrowsing-disable-auto-update",
    "--password-store=basic",
    "--use-mock-keychain",
]


_PW = None
_BROWSER = None
_CONTEXT = None
_PAGE = None
_USER_DATA_DIR = None


def _get_storage_path():
    """Get path for Playwright storage state (cookies, localStorage)."""
    global _USER_DATA_DIR
    if _USER_DATA_DIR is None:
        import tempfile, os as _os
        _USER_DATA_DIR = _os.path.join(tempfile.gettempdir(), "coagent_browser_storage.json")
    return _USER_DATA_DIR


def _ensure_browser(cookies=None, stealth=False):
    """Create fresh browser+context. Uses storage_state for cookie persistence
    across calls instead of launch_persistent_context to avoid Chromium lock issues.
    """
    global _PW, _CONTEXT, _PAGE
    sync_playwright, _playwright_error, missing = _load_playwright()
    if missing:
        return None, missing
    try:
        # Handle case where current thread has a running asyncio event loop
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # Running event loop detected - create a new one for this thread
                asyncio.set_event_loop(asyncio.new_event_loop())
            except RuntimeError:
                pass  # No running loop, we're fine
        except ImportError:
            pass
        
        # Always create fresh PW instance to avoid greenlet issues
        if _PW is not None:
            _PW = None  # Will be replaced, don't stop - context survives
        _PW = sync_playwright().start()
        
        # Close any existing context
        if _CONTEXT is not None:
            try:
                for p in _CONTEXT.pages:
                    try: p.close()
                    except Exception: pass
                _CONTEXT.close()
            except Exception:
                pass
            _CONTEXT = None
        
        launch_args = _STEALTH_ARGS if stealth else []
        _BROWSER_LOCAL = _PW.chromium.launch(headless=False, args=launch_args)
        
        context_kwargs = {}
        if stealth:
            import random as _srandom
            vp = _srandom.choice(_STEALTH_VIEWPORTS)
            ua = _srandom.choice(_STEALTH_USER_AGENTS)
            context_kwargs.update({
                "user_agent": ua,
                "viewport": vp,
                "locale": "en-US",
                "timezone_id": "America/Los_Angeles",
                "geolocation": {"latitude": 36.17, "longitude": -115.14},
                "permissions": ["geolocation"],
            })
        
        # Load saved storage state if exists
        storage_path = _get_storage_path()
        import os as _os
        if _os.path.exists(storage_path):
            context_kwargs["storage_state"] = storage_path
        
        _CONTEXT = _BROWSER_LOCAL.new_context(**context_kwargs)
        
        if stealth:
            _CONTEXT.add_init_script(_STEALTH_SCRIPT)
        if cookies and isinstance(cookies, list):
            _CONTEXT.add_cookies(cookies)
        
        _PAGE = _CONTEXT.new_page()
        return _PAGE, None
    except Exception as e:
        return None, _error(str(e), 500, type=type(e).__name__)


def _save_storage():
    """Save current context storage state for future calls."""
    if _CONTEXT is not None:
        try:
            _CONTEXT.storage_state(path=_get_storage_path())
            return True
        except Exception:
            pass
    return False


def _current_status():
    with _BROWSER_LOCK:
        try:
            ctx_alive = _CONTEXT is not None
            pages_count = len(_CONTEXT.pages) if ctx_alive else 0
            active_url = _PAGE.url if _PAGE and not _PAGE.is_closed() else None
            return {
                "open": ctx_alive,
                "pages": pages_count,
                "current_url": active_url,
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
            {"path": "/browser/navigate", "method": "POST", "desc": "Navigate to a URL, optionally with cookies + evaluate"},
            {"path": "/browser/workflow", "method": "POST", "desc": "Execute multi-step workflow in one session"},
            {"path": "/browser/click", "method": "POST", "desc": "Click by selector or text"},
            {"path": "/browser/fill", "method": "POST", "desc": "Fill an input"},
            {"path": "/browser/extract", "method": "POST", "desc": "Extract page text"},
            {"path": "/browser/elements", "method": "POST", "desc": "List interactive elements with selectors"},
            {"path": "/browser/screenshot", "method": "POST", "desc": "Capture browser screenshot"},
            {"path": "/browser/evaluate", "method": "POST", "desc": "Run JavaScript"},
            {"path": "/browser/cookies", "method": "POST", "desc": "Get or set cookies"},
            {"path": "/browser/cookies/import", "method": "POST", "desc": "Import cookies from Brave/Chrome profile"},
            {"path": "/browser/session/save", "method": "POST", "desc": "Save browser cookies to disk for persistence"},
            {"path": "/browser/session/load", "method": "POST", "desc": "Load saved session cookies"},
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
    url = url.strip()
    url_error = _navigation_url_error(url)
    if url_error:
        return _error(url_error, 403)
    cookies = data.get("cookies")
    evaluate = data.get("evaluate")  # optional JS to run after navigation
    stealth = _as_bool(data.get("stealth"), False)
    with _BROWSER_LOCK:
        page, error = _ensure_browser(cookies=cookies if isinstance(cookies, list) else None, stealth=stealth)
        if error:
            return error
        try:
            page.goto(url, wait_until=data.get("wait_until", "load"), timeout=_clamp_timeout(data, "timeout", 30000))
            result = {"status": "navigated", "url": page.url}
            if isinstance(evaluate, str) and evaluate:
                try:
                    eval_result = page.evaluate(evaluate)
                    result["evaluate"] = eval_result
                except Exception as e:
                    result["evaluate_error"] = str(e)
            return jsonify(result)
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
                page.click(selector, timeout=_clamp_timeout(data))
                target = {"selector": selector}
            elif isinstance(text, str) and text:
                page.get_by_text(text).click(timeout=_clamp_timeout(data))
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
            page.fill(selector, str(value), timeout=_clamp_timeout(data))
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
                text = page.locator(selector).inner_text(timeout=_clamp_timeout(data))
            else:
                text = page.inner_text("body", timeout=_clamp_timeout(data))
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
            context = page.context
            if action == "get":
                return jsonify({"cookies": context.cookies(), "url": page.url})
            if action == "set":
                cookies = data.get("cookies")
                if not isinstance(cookies, list):
                    return _error("cookies must be a list")
                context.add_cookies(cookies)
                return jsonify({"status": "set", "count": len(cookies), "url": page.url})
            return _error("action must be get or set")
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/cookies/import", methods=["POST"])
def route_browser_cookies_import():
    """Import cookies from Brave/Chrome browser profile for a domain."""
    import sqlite3, os, shutil, tempfile
    data = _json_payload()
    domain = data.get("domain", ".amazon.com")
    browser = data.get("browser", "brave").lower()  # brave or chrome
    
    # Determine cookie DB path
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if not localappdata:
        localappdata = os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local")
    
    if browser == "chrome":
        cookie_path = os.path.join(localappdata, "Google", "Chrome", "User Data", "Default", "Network", "Cookies")
    else:  # brave
        cookie_path = os.path.join(localappdata, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Network", "Cookies")
    
    if not os.path.exists(cookie_path):
        return _error(f"Cookie database not found at {cookie_path}", 404)
    
    try:
        # Copy the DB to avoid lock conflicts
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        shutil.copy2(cookie_path, tmp.name)
        
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute(
            "SELECT host_key, name, value, path, expires_utc, is_secure, is_httponly, same_site "
            "FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}",)
        )
        
        cookies = []
        for row in cur.fetchall():
            cookie = {
                "name": row["name"],
                "value": row["value"],
                "domain": row["host_key"],
                "path": row["path"] or "/",
                "secure": bool(row["is_secure"]),
                "httpOnly": bool(row["is_httponly"]),
            }
            if row["expires_utc"] and row["expires_utc"] > 0:
                cookie["expires"] = row["expires_utc"]
            if row["same_site"] >= 0:
                same_site_map = {0: "Strict", 1: "Lax", 2: "None"}
                cookie["sameSite"] = same_site_map.get(row["same_site"], "Lax")
            cookies.append(cookie)
        
        conn.close()
        os.unlink(tmp.name)
        
        return jsonify({"cookies": cookies, "count": len(cookies), "domain": domain})
    except Exception as e:
        return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/network", methods=["POST"])
def route_browser_network():
    """Navigate to a URL and capture all network requests (XHR, fetch, etc)."""
    data = _json_payload()
    url = data.get("url")
    if not isinstance(url, str) or not url:
        return _error("url is required")
    url_error = _navigation_url_error(url)
    if url_error:
        return _error(url_error, 403)
    
    cookies = data.get("cookies")
    filter_url = data.get("filter")  # optional URL substring filter
    stealth = _as_bool(data.get("stealth"), False)
    
    with _BROWSER_LOCK:
        page, error = _ensure_browser(cookies=cookies if isinstance(cookies, list) else None, stealth=stealth)
        if error:
            return error
        
        requests_log = []
        
        def on_request(request):
            requests_log.append({
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": request.post_data[:500] if request.post_data else None,
                "resource_type": request.resource_type,
                "timestamp": request.headers.get("date", ""),
            })
        
        def on_response(response):
            for req in requests_log:
                if req["url"] == response.url:
                    req["status"] = response.status
                    req["status_text"] = response.status_text
                    try:
                        body = response.body()
                        req["body"] = body[:2000].decode("utf-8", errors="replace") if body else None
                        req["body_size"] = len(body) if body else 0
                    except Exception:
                        req["body"] = "(binary/streaming)"
                    break
        
        try:
            page.on("request", on_request)
            page.on("response", on_response)
            
            page.goto(url, wait_until=data.get("wait_until", "networkidle"), timeout=_clamp_timeout(data, "timeout", 30000))
            
            # Filter if requested
            results = requests_log
            if isinstance(filter_url, str) and filter_url:
                results = [r for r in results if filter_url.lower() in r["url"].lower()]
            
            return jsonify({
                "url": page.url,
                "total_requests": len(requests_log),
                "filtered": len(results) if filter_url else len(requests_log),
                "requests": results[-100:],  # last 100, most recent
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/workflow", methods=["POST"])
def route_browser_workflow():
    """Execute a sequence of browser actions in a single session.
    
    Accepts:
      - cookies: optional list of cookies to set before any actions
      - steps: list of action objects
    
    Each step: {"action": "...", ...params}
    
    Supported actions:
      - navigate: {"action": "navigate", "url": "..."}
      - click: {"action": "click", "selector": "..."} or {"action": "click", "text": "..."}
      - fill: {"action": "fill", "selector": "...", "value": "..."}
      - extract: {"action": "extract"} or {"action": "extract", "selector": "..."}
      - evaluate: {"action": "evaluate", "script": "..."}
      - screenshot: {"action": "screenshot"}
      - wait: {"action": "wait", "ms": 1000} or {"action": "wait", "selector": "..."}
      - scroll: {"action": "scroll", "pixels": 500} or {"action": "scroll", "direction": "down|up"}
      - press: {"action": "press", "keys": ["Enter"]} or ["ctrl", "a"]
      - select: {"action": "select", "selector": "...", "value": "..."}
      - check: {"action": "check", "selector": "..."}
      - uncheck: {"action": "uncheck", "selector": "..."}
      - hover: {"action": "hover", "selector": "..."}
    """
    import traceback as _tb
    data = _json_payload()
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return _error("steps (list) is required")
    
    cookies = data.get("cookies")
    
    # Auto-load session cookies if requested
    if _as_bool(data.get("load_session"), False):
        import os as _os2, json as _json2
        sf = _get_session_file()
        if _os2.path.exists(sf):
            with open(sf) as f:
                saved = _json2.load(f)
            if isinstance(saved, list):
                cookies = saved if not cookies else cookies + saved
    
    stealth = _as_bool(data.get("stealth"), False)
    
    with _BROWSER_LOCK:
        page, error = _ensure_browser(cookies=cookies if isinstance(cookies, list) else None, stealth=stealth)
        if error:
            return error
        
        results = []
        try:
            for i, step in enumerate(steps):
                action = step.get("action", "")
                step_result = {"step": i, "action": action}
                
                try:
                    if action == "navigate":
                        url = step.get("url")
                        if not url:
                            step_result["error"] = "url required"
                        else:
                            url_error = _navigation_url_error(url)
                            if url_error:
                                step_result["error"] = url_error
                            else:
                                timeout = _clamp_timeout(step, "timeout", 30000)
                                page.goto(url, wait_until=step.get("wait_until", "load"), timeout=timeout)
                                step_result["url"] = page.url
                    
                    elif action == "click":
                        selector = step.get("selector")
                        text = step.get("text")
                        timeout = _clamp_timeout(step, "timeout", 10000)
                        if selector:
                            page.click(selector, timeout=timeout)
                            step_result["target"] = selector
                        elif text:
                            page.get_by_text(text).click(timeout=timeout)
                            step_result["target"] = text
                        else:
                            step_result["error"] = "selector or text required"
                    
                    elif action == "fill":
                        selector = step.get("selector")
                        value = step.get("value")
                        if not selector:
                            step_result["error"] = "selector required"
                        elif value is None:
                            step_result["error"] = "value required"
                        else:
                            page.fill(selector, str(value), timeout=_clamp_timeout(step))
                            step_result["filled"] = True
                    
                    elif action == "extract":
                        selector = step.get("selector")
                        if selector:
                            text = page.locator(selector).inner_text(timeout=_clamp_timeout(step, "timeout", 10000))
                        else:
                            text = page.inner_text("body", timeout=_clamp_timeout(step, "timeout", 10000))
                        step_result["text"] = text
                        step_result["chars"] = len(text)
                    
                    elif action == "evaluate":
                        script = step.get("script")
                        if not script:
                            step_result["error"] = "script required"
                        else:
                            result = page.evaluate(script)
                            step_result["result"] = result
                    
                    elif action == "screenshot":
                        full_page = _as_bool(step.get("full_page"), False)
                        data_bytes = page.screenshot(full_page=full_page)
                        step_result["data"] = base64.b64encode(data_bytes).decode("ascii")
                        step_result["format"] = "png"
                    
                    elif action == "wait":
                        ms = step.get("ms")
                        selector = step.get("selector")
                        if selector:
                            page.wait_for_selector(selector, timeout=_clamp_timeout(step, "timeout", 15000))
                            step_result["waited_for"] = selector
                        elif ms:
                            import time as _time
                            _time.sleep(ms / 1000.0)
                            step_result["waited_ms"] = ms
                        else:
                            step_result["error"] = "ms or selector required"
                    
                    elif action == "scroll":
                        pixels = step.get("pixels")
                        direction = step.get("direction", "down")
                        if pixels:
                            page.evaluate(f"window.scrollBy(0, {pixels})")
                            step_result["scrolled"] = pixels
                        else:
                            amount = 800 if direction == "down" else -800
                            page.evaluate(f"window.scrollBy(0, {amount})")
                            step_result["scrolled"] = direction
                    
                    elif action == "press":
                        keys = step.get("keys")
                        if isinstance(keys, list) and keys:
                            page.keyboard.press("+".join(keys))
                            step_result["pressed"] = keys
                        elif isinstance(keys, str):
                            page.keyboard.press(keys)
                            step_result["pressed"] = keys
                        else:
                            step_result["error"] = "keys (list or string) required"
                    
                    elif action == "select":
                        selector = step.get("selector")
                        value = step.get("value")
                        if selector and value is not None:
                            page.select_option(selector, str(value), timeout=_clamp_timeout(step))
                            step_result["selected"] = value
                        else:
                            step_result["error"] = "selector and value required"
                    
                    elif action == "check":
                        selector = step.get("selector")
                        if selector:
                            page.check(selector, timeout=_clamp_timeout(step))
                            step_result["checked"] = selector
                        else:
                            step_result["error"] = "selector required"
                    
                    elif action == "uncheck":
                        selector = step.get("selector")
                        if selector:
                            page.uncheck(selector, timeout=_clamp_timeout(step))
                            step_result["unchecked"] = selector
                        else:
                            step_result["error"] = "selector required"
                    
                    elif action == "hover":
                        selector = step.get("selector")
                        if selector:
                            page.hover(selector, timeout=_clamp_timeout(step))
                            step_result["hovered"] = selector
                        else:
                            step_result["error"] = "selector required"
                    
                    elif action == "human_type":
                        import random, time as _htime
                        selector = step.get("selector")
                        text = step.get("text", "")
                        wpm = step.get("wpm", 40)  # words per minute
                        if selector:
                            page.click(selector)
                        delay_per_char = 60.0 / (wpm * 5)  # 5 chars per word avg
                        for char in text:
                            page.keyboard.type(char, delay=delay_per_char * random.uniform(0.5, 1.5))
                            _htime.sleep(delay_per_char * random.uniform(0.3, 0.7))
                        step_result["human_typed"] = len(text)
                        step_result["wpm"] = wpm
                    
                    elif action == "mousemove":
                        import random, time as _mtime
                        to_x = step.get("x", 0)
                        to_y = step.get("y", 0)
                        steps = step.get("steps", 20)
                        # Move mouse in small increments
                        for i in range(steps):
                            t = (i + 1) / steps
                            # Bezier-like easing
                            eased_t = t * t * (3 - 2 * t)
                            cur_x = int(to_x * eased_t)
                            cur_y = int(to_y * eased_t)
                            page.mouse.move(cur_x, cur_y)
                            _mtime.sleep(random.uniform(0.005, 0.02))
                        step_result["moved_to"] = [to_x, to_y]
                    
                    elif action == "random_delay":
                        import random, time as _rdtime
                        min_ms = step.get("min_ms", 200)
                        max_ms = step.get("max_ms", 1500)
                        delay = random.uniform(min_ms, max_ms) / 1000.0
                        _rdtime.sleep(delay)
                        step_result["delayed_ms"] = int(delay * 1000)
                    
                    elif action == "scroll_human":
                        import random, time as _shtime
                        pixels = step.get("pixels", 500)
                        direction = step.get("direction", "down")
                        total = pixels if direction == "down" else -pixels
                        chunks = random.randint(5, 12)
                        for i in range(chunks):
                            chunk = total // chunks
                            page.mouse.wheel(0, chunk)
                            _shtime.sleep(random.uniform(0.03, 0.12))
                        step_result["scrolled_human"] = total
                    
                    elif action == "console":
                        # Capture console messages
                        msgs = []
                        def _on_console(msg):
                            msgs.append({"type": msg.type, "text": msg.text})
                        page.on("console", _on_console)
                        # If a script is provided, evaluate it and capture its console output
                        script = step.get("script")
                        if script:
                            page.evaluate(script)
                        # Wait a bit for async console messages
                        import time as _ctime
                        _ctime.sleep(step.get("wait_ms", 500) / 1000.0)
                        page.remove_listener("console", _on_console)
                        step_result["messages"] = msgs[-50:]  # last 50
                    
                    else:
                        step_result["error"] = f"unknown action: {action}"
                
                except Exception as e:
                    step_result["error"] = str(e)
                    step_result["error_type"] = type(e).__name__
                
                results.append(step_result)
                
                # Stop on error unless continue_on_error is set
                if "error" in step_result and not _as_bool(data.get("continue_on_error"), False):
                    break
            
            # Auto-save session if requested
            save_msg = None
            if _as_bool(data.get("save_session"), False):
                try:
                    import json as _json3
                    cookies_list = page.context.cookies()
                    with open(_get_session_file(), "w") as f:
                        _json3.dump(cookies_list, f)
                    save_msg = f"Saved {len(cookies_list)} cookies"
                except Exception as e:
                    save_msg = f"Save failed: {e}"
            
            response = {
                "status": "completed" if not any("error" in r for r in results) else "partial",
                "url": page.url,
                "steps_executed": len(results),
                "results": results,
            }
            _save_storage()  # Always save storage after workflow
            if save_msg:
                response["session"] = save_msg
            return jsonify(response)
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__, traceback=_tb.format_exc()[:2000])


@browser_bp.route("/browser/elements", methods=["POST"])
def route_browser_elements():
    """List interactive elements on the current page with selectors and text."""
    data = _json_payload()
    filter_text = data.get("filter")  # optional text filter
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            script = """
            () => {
                const elements = [];
                const selectors = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [onclick]';
                document.querySelectorAll(selectors).forEach((el, i) => {
                    if (el.offsetParent === null) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;
                    const text = (el.textContent || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100);
                    const tag = el.tagName.toLowerCase();
                    const type = el.type || '';
                    const id = el.id || '';
                    const className = (typeof el.className === 'string' ? el.className : '') || '';
                    const href = el.href || '';
                    const name = el.name || '';
                    const dataTestId = el.getAttribute('data-testid') || '';
                    
                    let suggestedSelector = '';
                    if (id) suggestedSelector = '#' + id;
                    else if (dataTestId) suggestedSelector = '[data-testid="' + dataTestId + '"]';
                    else if (name) suggestedSelector = tag + '[name="' + name + '"]';
                    else if (type) suggestedSelector = tag + '[type="' + type + '"]';
                    
                    elements.push({
                        index: i,
                        tag: tag,
                        type: type,
                        text: text,
                        id: id,
                        name: name,
                        href: href,
                        className: className.substring(0, 80),
                        suggestedSelector: suggestedSelector,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                    });
                });
                return elements;
            }
            """
            elements = page.evaluate(script)
            
            if isinstance(filter_text, str) and filter_text:
                ft = filter_text.lower()
                elements = [e for e in elements if ft in e.get('text', '').lower() or ft in e.get('id', '').lower() or ft in e.get('name', '').lower()]
            
            return jsonify({
                "url": page.url,
                "count": len(elements),
                "elements": elements[:200],
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


_BROWSER_SESSION_FILE = None


def _get_session_file():
    global _BROWSER_SESSION_FILE
    if _BROWSER_SESSION_FILE is None:
        import tempfile, os as _os
        _BROWSER_SESSION_FILE = _os.path.join(tempfile.gettempdir(), "coagent_browser_session.json")
    return _BROWSER_SESSION_FILE


@browser_bp.route("/browser/session/save", methods=["POST"])
def route_browser_session_save():
    """Save current browser storage state (cookies, localStorage) to disk."""
    with _BROWSER_LOCK:
        if _save_storage():
            return jsonify({"status": "saved", "file": _get_storage_path()})
        return jsonify({"status": "no_context", "note": "No active browser context to save"})


@browser_bp.route("/browser/session/load", methods=["POST"])
def route_browser_session_load():
    """Return saved session cookies (for passing to navigate/workflow as 'cookies' param)."""
    import json as _json, os as _os
    session_file = _get_session_file()
    if not _os.path.exists(session_file):
        return jsonify({"cookies": [], "count": 0, "note": "No saved session"})
    try:
        with open(session_file) as f:
            cookies = _json.load(f)
        return jsonify({"cookies": cookies, "count": len(cookies)})
    except Exception as e:
        return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/close", methods=["POST"])
def route_browser_close():
    global _PW, _BROWSER, _CONTEXT, _PAGE
    with _BROWSER_LOCK:
        errors = []
        if _CONTEXT:
            try:
                # Close all context pages first
                for p in _CONTEXT.pages:
                    try:
                        p.close()
                    except Exception:
                        pass
                _CONTEXT.close()
            except Exception as e:
                errors.append(f"context: {e}")
        if _PW:
            try:
                _PW.stop()
            except Exception as e:
                errors.append(f"playwright: {e}")
        _PW = _BROWSER = _CONTEXT = _PAGE = None
        if errors:
            return _error("; ".join(errors), 500)
        return jsonify({"status": "closed"})


def register_routes(app, state, require_auth):
    app.register_blueprint(browser_bp)
    _wrap_registered_blueprint_routes(app, browser_bp.name, require_auth)
