"""Patchright/Playwright browser control routes."""

import base64
import threading
import urllib.parse
from pathlib import Path

import json as _json
from collections import deque
from flask import Blueprint, jsonify, request

from routes_bypass import _json_payload

# Patch asyncio for Playwright sync API
try:
    import nest_asyncio, asyncio
    nest_asyncio.apply()
except (ImportError, RuntimeError):
    pass
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


_USER_DATA_DIR = None

# Console messages captured from active page
_CONSOLE_MESSAGES: deque = deque(maxlen=200)
# Dialog event log + next-action setting (AI pre-sets before triggering action)
_DIALOG_LOG: deque = deque(maxlen=50)
_NEXT_DIALOG_ACTION: dict = {"action": "dismiss", "text": ""}
# Client-side navigation history
_NAV_HISTORY: deque = deque(maxlen=100)


def _compact_a11y(node, depth=0, max_depth=6):
    """Recursively compact an accessibility tree node to a terse dict."""
    if node is None or depth > max_depth:
        return None
    out = {}
    role = node.get("role", "")
    name = (node.get("name") or "").strip()[:120]
    value = node.get("value", "")
    if isinstance(value, str):
        value = value.strip()[:120]
    if role:
        out["role"] = role
    if name:
        out["name"] = name
    if value:
        out["value"] = value
    for attr in ("checked", "disabled", "expanded", "level", "pressed", "selected", "required"):
        if node.get(attr) is not None:
            out[attr] = node[attr]
    children = node.get("children") or []
    compact = [_compact_a11y(c, depth + 1, max_depth) for c in children]
    compact = [c for c in compact if c]
    if compact:
        out["children"] = compact
    return out or None


def _setup_page_listeners(page):
    """Attach console + dialog event listeners to a newly created page."""
    def _on_console(msg):
        _CONSOLE_MESSAGES.append({"type": msg.type, "text": msg.text, "url": page.url})

    def _on_dialog(dialog):
        action = _NEXT_DIALOG_ACTION.get("action", "dismiss")
        text = _NEXT_DIALOG_ACTION.get("text", "")
        _DIALOG_LOG.append({
            "type": dialog.type,
            "message": dialog.message,
            "default_value": dialog.default_value if dialog.type == "prompt" else None,
            "action_taken": action,
            "text_sent": text,
        })
        try:
            if action == "accept":
                dialog.accept(text) if text else dialog.accept()
            else:
                dialog.dismiss()
        except Exception:
            pass

    page.on("console", _on_console)
    page.on("dialog", _on_dialog)


def _get_storage_path():
    """Get path for Playwright storage state (cookies, localStorage)."""
    global _USER_DATA_DIR
    if _USER_DATA_DIR is None:
        import tempfile, os as _os
        _USER_DATA_DIR = _os.path.join(tempfile.gettempdir(), "coagent_browser_storage.json")
    return _USER_DATA_DIR


_BROWSER_EXECUTOR = None


def _run_on_pw_thread(fn, *args, **kwargs):
    """Run on single thread to avoid greenlet issues when asyncio is active."""
    global _BROWSER_EXECUTOR
    if _BROWSER_EXECUTOR is None:
        import concurrent.futures
        _BROWSER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")
    return _BROWSER_EXECUTOR.submit(fn, *args, **kwargs).result(timeout=300)


def _ensure_browser(cookies=None, stealth=False):
    """Create or reuse browser context."""
    return _ensure_browser_inner(cookies, stealth)


_CDP_URL = None  # Chrome DevTools Protocol URL for persistent browser


def _get_cdp_browser():
    """Launch a persistent Chromium via CDP that survives across calls."""
    global _CDP_URL
    if _CDP_URL is not None:
        return _CDP_URL
    
    import subprocess, tempfile, os as _os, time as _time
    
    user_data = _os.path.join(tempfile.gettempdir(), "coagent_chrome_profile")
    _os.makedirs(user_data, exist_ok=True)
    
    # Find Chromium on Windows
    chrome_exe = None
    candidates = [
        _os.path.expandvars("%LOCALAPPDATA%\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe"),
        _os.path.expandvars("%LOCALAPPDATA%\\ms-playwright\\chromium-*\\chrome-win64\\chrome.exe"),
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ]
    import glob
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                chrome_exe = matches[0]
                break
        elif _os.path.exists(c):
            chrome_exe = c
            break
    
    if not chrome_exe:
        return None
    
    # Find a free port
    import socket
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    
    _CDP_URL = f"http://127.0.0.1:{port}"
    
    # Kill any existing Chrome using same user_data_dir
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], 
                       capture_output=True, timeout=5)
    except Exception:
        pass
    _time.sleep(1)
    
    # Launch Chrome with remote debugging
    args = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=TranslateUI",
        "--window-size=1280,900",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _time.sleep(3)
    
    # Verify CDP is reachable
    import urllib.request
    for _ in range(5):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return _CDP_URL
        except Exception:
            _time.sleep(1)
    
    # Chrome didn't start - reset and return None
    _CDP_URL = None
    return None


def _ensure_browser_inner(cookies=None, stealth=False):
    """Runs on single thread. Reuses browser context if alive."""
    global _PW, _CONTEXT, _PAGE, _BROWSER
    
    # Reuse existing browser if alive
    if _BROWSER is not None and _CONTEXT is not None:
        try:
            pages = _CONTEXT.pages
            if pages:
                _PAGE = pages[0]
                return _PAGE, None
        except Exception:
            pass
    
    sync_playwright, _playwright_error, missing = _load_playwright()
    if missing:
        return None, missing
    
    try:
        # Don't stop old PW — cross-thread greenlet issue
        _PW = sync_playwright().start()
        _CONTEXT = None
        
        launch_args = _STEALTH_ARGS if stealth else []
        _BROWSER = _PW.chromium.launch(headless=False, args=launch_args)
        
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
        
        # Load saved storage if exists
        storage_path = _get_storage_path()
        import os as _os
        if _os.path.exists(storage_path):
            context_kwargs["storage_state"] = storage_path
        
        _CONTEXT = _BROWSER.new_context(**context_kwargs)
        
        # Don't block popups — Amazon opens review form in new window
        try:
            _CONTEXT.grant_permissions(["popups"])
        except Exception:
            pass

        # Capture popup/new windows and attach listeners
        def _on_new_page(p):
            setattr(p, "_coagent_popup", True)
            _setup_page_listeners(p)
        _CONTEXT.on("page", _on_new_page)
        
        if stealth:
            _CONTEXT.add_init_script(_STEALTH_SCRIPT)
        if cookies and isinstance(cookies, list):
            _CONTEXT.add_cookies(cookies)
        
        _PAGE = _CONTEXT.new_page()
        _setup_page_listeners(_PAGE)
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
            {"path": "/browser/status", "method": "GET", "desc": "Browser open/closed state"},
            {"path": "/browser/snapshot", "method": "POST", "desc": "AI primary: page title + text + optional accessibility tree. mode=text|accessibility|both"},
            {"path": "/browser/navigate", "method": "POST", "desc": "Navigate to URL. Returns title. Pass snapshot=true for body text snippet."},
            {"path": "/browser/back", "method": "POST", "desc": "Go back in history"},
            {"path": "/browser/forward", "method": "POST", "desc": "Go forward in history"},
            {"path": "/browser/refresh", "method": "POST", "desc": "Reload the current page"},
            {"path": "/browser/stop", "method": "POST", "desc": "Stop page loading"},
            {"path": "/browser/url", "method": "GET", "desc": "Get current URL"},
            {"path": "/browser/title", "method": "GET", "desc": "Get current page title"},
            {"path": "/browser/source", "method": "GET", "desc": "Get full HTML source"},
            {"path": "/browser/history", "method": "GET", "desc": "Navigation history (URL+title) for this session"},
            {"path": "/browser/click", "method": "POST", "desc": "Click by selector or text. Returns element_text, url_changed, title."},
            {"path": "/browser/fill", "method": "POST", "desc": "Fill input. Returns value_confirmed and accepted flag."},
            {"path": "/browser/press", "method": "POST", "desc": "Press key or combo (Enter, Escape, Control+a). Optional selector."},
            {"path": "/browser/hover", "method": "POST", "desc": "Hover over selector"},
            {"path": "/browser/focus", "method": "POST", "desc": "Focus an element"},
            {"path": "/browser/extract", "method": "POST", "desc": "Extract text (mode=text) or structured data (mode=structured: links/buttons/inputs/headings)"},
            {"path": "/browser/elements", "method": "POST", "desc": "List interactive elements with suggested selectors"},
            {"path": "/browser/wait", "method": "POST", "desc": "Wait for selector state, text presence, or URL pattern. Essential for SPAs."},
            {"path": "/browser/screenshot", "method": "POST", "desc": "Screenshot as base64 PNG or saved to path"},
            {"path": "/browser/evaluate", "method": "POST", "desc": "Run arbitrary JavaScript"},
            {"path": "/browser/scroll-to", "method": "POST", "desc": "Scroll to selector or x/y coordinates"},
            {"path": "/browser/console", "method": "GET", "desc": "Recent console messages. ?level=error|warn|log&limit=50"},
            {"path": "/browser/dialog", "method": "GET", "desc": "Dialog log + next-action setting"},
            {"path": "/browser/dialog/accept", "method": "POST", "desc": "Pre-set next dialog to accept. Optional text for prompt dialogs."},
            {"path": "/browser/dialog/dismiss", "method": "POST", "desc": "Pre-set next dialog to dismiss (default)"},
            {"path": "/browser/tabs", "method": "GET", "desc": "List all open tabs"},
            {"path": "/browser/new-tab", "method": "POST", "desc": "Open new tab, optionally navigate to URL"},
            {"path": "/browser/close-tab", "method": "POST", "desc": "Close tab by index (default: active)"},
            {"path": "/browser/switch-tab", "method": "POST", "desc": "Switch active tab by index"},
            {"path": "/browser/pages", "method": "GET", "desc": "List open pages/popups (alias: /browser/tabs)"},
            {"path": "/browser/viewport", "method": "GET", "desc": "Get viewport size"},
            {"path": "/browser/viewport", "method": "POST", "desc": "Resize viewport: width, height"},
            {"path": "/browser/workflow", "method": "POST", "desc": "Execute multi-step action sequence in one call"},
            {"path": "/browser/cookies", "method": "POST", "desc": "Get (action=get) or set (action=set) cookies"},
            {"path": "/browser/cookies/set", "method": "POST", "desc": "Set cookies directly: {cookies: [...]}"},
            {"path": "/browser/cookies/import", "method": "POST", "desc": "Import from Brave/Chrome profile"},
            {"path": "/browser/network", "method": "POST", "desc": "Navigate + capture all network requests"},
            {"path": "/browser/session/save", "method": "POST", "desc": "Save storage state to disk"},
            {"path": "/browser/session/load", "method": "POST", "desc": "Load saved session"},
            {"path": "/browser/close", "method": "POST", "desc": "Close browser and free resources"},
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
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            _NAV_HISTORY.append({"url": page.url, "title": title})
            result = {"status": "navigated", "url": page.url, "title": title}
            if _as_bool(data.get("snapshot"), False):
                try:
                    result["snippet"] = page.inner_text("body", timeout=5000)[:1000]
                except Exception:
                    pass
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
            url_before = page.url
            if isinstance(selector, str) and selector:
                element_text = ""
                try:
                    element_text = (page.locator(selector).first.inner_text(timeout=2000) or "").strip()[:100]
                except Exception:
                    pass
                page.click(selector, timeout=_clamp_timeout(data))
                target = {"selector": selector, "element_text": element_text}
            elif isinstance(text, str) and text:
                page.get_by_text(text).click(timeout=_clamp_timeout(data))
                target = {"text": text, "element_text": text}
            else:
                return _error("selector or text is required")
            new_url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            return jsonify({
                "status": "clicked",
                "url": new_url,
                "url_changed": new_url != url_before,
                "url_before": url_before,
                "title": title,
                **target,
            })
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
            confirmed = None
            try:
                confirmed = page.locator(selector).input_value(timeout=2000)
            except Exception:
                pass
            return jsonify({
                "status": "filled",
                "selector": selector,
                "value_set": str(value),
                "value_confirmed": confirmed,
                "accepted": (confirmed == str(value)) if confirmed is not None else None,
                "url": page.url,
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


_EXTRACT_STRUCTURED_SCRIPT = """() => {
    const links = [];
    document.querySelectorAll('a[href]').forEach(el => {
        const text = (el.innerText || el.getAttribute('aria-label') || '').trim().substring(0, 100);
        if (text) links.push({text, href: el.href});
    });
    const buttons = [];
    document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]').forEach(el => {
        if (el.offsetParent === null) return;
        const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().substring(0, 100);
        const id = el.id ? '#' + el.id : '';
        const name = el.name ? '[name="' + el.name + '"]' : '';
        buttons.push({text, selector: id || name || el.tagName.toLowerCase(), disabled: el.disabled});
    });
    const inputs = [];
    document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]),textarea,select').forEach(el => {
        if (el.offsetParent === null) return;
        const label = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
        const labelText = label ? label.innerText.trim() : (el.getAttribute('aria-label') || el.placeholder || '');
        const id = el.id ? '#' + el.id : '';
        const name = el.name ? '[name="' + el.name + '"]' : '';
        inputs.push({
            label: labelText.substring(0, 80),
            type: el.type || el.tagName.toLowerCase(),
            name: el.name || '',
            value: (el.value || '').substring(0, 200),
            placeholder: (el.placeholder || '').substring(0, 80),
            selector: id || name || el.tagName.toLowerCase(),
            required: el.required,
        });
    });
    const headings = [];
    document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(el => {
        headings.push({level: parseInt(el.tagName[1]), text: el.innerText.trim().substring(0, 200)});
    });
    return {links: links.slice(0, 100), buttons: buttons.slice(0, 60), inputs, headings};
}"""


@browser_bp.route("/browser/extract", methods=["POST"])
def route_browser_extract():
    """Extract text or structured data (links, buttons, inputs, headings) from the page.

    mode='text' (default): return inner text of page or selector.
    mode='structured': return links, buttons, inputs, headings as JSON.
    """
    data = _json_payload()
    selector = data.get("selector")
    mode = data.get("mode", "text")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if mode == "structured" or (mode != "text" and not selector):
                structured = page.evaluate(_EXTRACT_STRUCTURED_SCRIPT)
                body_text = ""
                try:
                    body_text = page.inner_text("body", timeout=5000)
                except Exception:
                    pass
                return jsonify({
                    "mode": "structured",
                    "url": page.url,
                    "title": page.title(),
                    **structured,
                    "text": body_text[:3000],
                    "text_chars": len(body_text),
                })
            # Text mode (backward-compatible)
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
                    
                    elif action == "pages":
                        pages = page.context.pages
                        pages_info = []
                        switch_idx = step.get("switch")
                        for i, p in enumerate(pages):
                            try:
                                pages_info.append({"index": i, "url": p.url, "title": p.title() or ""})
                            except Exception:
                                pages_info.append({"index": i, "url": "error", "title": ""})
                        step_result["pages"] = pages_info
                        step_result["count"] = len(pages)
                        if switch_idx is not None and 0 <= switch_idx < len(pages):
                            page = pages[switch_idx]
                            step_result["switched_to"] = switch_idx
                    
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
                        # Start from current mouse position, not (0,0)
                        try:
                            from_x = page.evaluate("() => window.mouseX || 0")
                            from_y = page.evaluate("() => window.mouseY || 0")
                        except Exception:
                            from_x, from_y = 0, 0
                        # Move mouse in small increments, easing from current to target
                        for i in range(steps):
                            t = (i + 1) / steps
                            # Bezier-like easing
                            eased_t = t * t * (3 - 2 * t)
                            cur_x = int(from_x + (to_x - from_x) * eased_t)
                            cur_y = int(from_y + (to_y - from_y) * eased_t)
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
                        try:
                            # If a script is provided, evaluate it and capture its console output
                            script = step.get("script")
                            if script:
                                page.evaluate(script)
                            # Wait a bit for async console messages
                            import time as _ctime
                            _ctime.sleep(step.get("wait_ms", 500) / 1000.0)
                        finally:
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


@browser_bp.route("/browser/pages", methods=["GET"])
def route_browser_pages():
    """List all open pages/popups and switch to one."""
    with _BROWSER_LOCK:
        if _CONTEXT is None:
            return jsonify({"pages": [], "count": 0})
        global _PAGE
        switch_to = request.args.get("switch", type=int)
        pages = _CONTEXT.pages
        result = {"count": len(pages), "active": pages.index(_PAGE) if _PAGE in pages else -1}
        result["pages"] = [
            {"index": i, "url": p.url, "title": (p.title() or ""), "closed": p.is_closed()}
            for i, p in enumerate(pages)
        ]
        if switch_to is not None and 0 <= switch_to < len(pages):
            _PAGE = pages[switch_to]
            result["switched_to"] = switch_to
        return jsonify(result)


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


# ---------------------------------------------------------------------------
# Snapshot — #1 AI-facing endpoint: "what do I see right now?"
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/snapshot", methods=["POST"])
def route_browser_snapshot():
    """Return a compact accessibility tree and/or clean text of the current page.

    mode='text' (default): body text + title. Fastest.
    mode='accessibility': Playwright accessibility tree (structured roles/names).
    mode='both': both.
    Pass snapshot=true to /browser/navigate instead for a combined navigate+snapshot.
    """
    data = _json_payload()
    mode = data.get("mode", "text")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            result = {"url": page.url}
            try:
                result["title"] = page.title()
            except Exception:
                result["title"] = ""
            if mode in ("accessibility", "both"):
                try:
                    tree = page.accessibility.snapshot()
                    result["accessibility_tree"] = _compact_a11y(tree)
                except Exception as e:
                    result["accessibility_error"] = str(e)
            if mode in ("text", "both"):
                try:
                    text = page.inner_text("body", timeout=8000)
                    result["text"] = text[:6000]
                    result["text_chars"] = len(text)
                except Exception as e:
                    result["text_error"] = str(e)
            return jsonify(result)
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Wait — essential for SPAs and dynamic content
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/wait", methods=["POST"])
def route_browser_wait():
    """Wait for a condition before the next action. Essential for SPAs.

    Provide ONE of:
      selector + state: wait for CSS selector in state visible|hidden|attached|detached.
      text: wait for this string to appear in body text.
      url: wait for page URL to contain this string.
    """
    data = _json_payload()
    selector = data.get("selector")
    text = data.get("text")
    url_pattern = data.get("url")
    state = data.get("state", "visible")
    timeout = _clamp_timeout(data, "timeout", 15000)
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if isinstance(selector, str) and selector:
                page.wait_for_selector(selector, state=state, timeout=timeout)
                return jsonify({"waited_for": "selector", "selector": selector, "state": state, "url": page.url})
            if isinstance(text, str) and text:
                page.wait_for_function(
                    f"() => document.body.innerText.includes({_json.dumps(text)})",
                    timeout=timeout,
                )
                return jsonify({"waited_for": "text", "text": text, "url": page.url})
            if isinstance(url_pattern, str) and url_pattern:
                page.wait_for_url(f"**{url_pattern}**", timeout=timeout)
                return jsonify({"waited_for": "url", "url": page.url})
            return _error("selector, text, or url is required")
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Key press and element interactions
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/press", methods=["POST"])
def route_browser_press():
    """Press a key or combo. key examples: 'Enter', 'Escape', 'Tab', 'Control+a'.
    Optionally target a selector (focused element by default).
    """
    data = _json_payload()
    key = data.get("key")
    selector = data.get("selector")
    if not isinstance(key, str) or not key:
        return _error("key is required (e.g. 'Enter', 'Escape', 'Control+a', 'Tab')")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            url_before = page.url
            if isinstance(selector, str) and selector:
                page.press(selector, key, timeout=_clamp_timeout(data))
            else:
                page.keyboard.press(key)
            return jsonify({
                "pressed": key,
                "selector": selector,
                "url": page.url,
                "url_changed": page.url != url_before,
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/hover", methods=["POST"])
def route_browser_hover():
    """Hover the mouse over an element. Useful for revealing tooltips/dropdowns."""
    data = _json_payload()
    selector = data.get("selector")
    if not isinstance(selector, str) or not selector:
        return _error("selector is required")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.hover(selector, timeout=_clamp_timeout(data))
            return jsonify({"hovered": selector, "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/focus", methods=["POST"])
def route_browser_focus():
    """Focus an element (useful before typing with /browser/press)."""
    data = _json_payload()
    selector = data.get("selector")
    if not isinstance(selector, str) or not selector:
        return _error("selector is required")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.focus(selector, timeout=_clamp_timeout(data))
            value = None
            try:
                value = page.locator(selector).input_value(timeout=1000)
            except Exception:
                pass
            return jsonify({"focused": selector, "current_value": value, "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Console messages
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/console", methods=["GET"])
def route_browser_console():
    """Get recent console messages (log, warn, error) from the active page.
    Query params: limit (default 50, max 200), level (log|warn|error|info).
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    level = request.args.get("level")
    msgs = list(_CONSOLE_MESSAGES)
    if level:
        msgs = [m for m in msgs if m.get("type") == level]
    active_url = None
    with _BROWSER_LOCK:
        if _PAGE and not _PAGE.is_closed():
            try:
                active_url = _PAGE.url
            except Exception:
                pass
    return jsonify({"count": len(msgs), "messages": msgs[-limit:], "url": active_url})


# ---------------------------------------------------------------------------
# Dialog handling — pre-set next dialog response before triggering action
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/dialog", methods=["GET"])
def route_browser_dialog():
    """Get dialog event log and current next-action setting.
    To pre-set a response: POST /browser/dialog/accept or /browser/dialog/dismiss
    BEFORE the action that triggers the dialog (e.g., a button click).
    """
    return jsonify({
        "log": list(_DIALOG_LOG)[-20:],
        "next_action": _NEXT_DIALOG_ACTION.copy(),
        "note": "Call /dialog/accept or /dialog/dismiss before triggering the action that opens the dialog.",
    })


@browser_bp.route("/browser/dialog/accept", methods=["POST"])
def route_browser_dialog_accept():
    """Pre-set the next dialog to be accepted. For prompt dialogs, pass 'text'."""
    data = _json_payload()
    text = str(data.get("text", ""))
    _NEXT_DIALOG_ACTION.update({"action": "accept", "text": text})
    return jsonify({"next_action": _NEXT_DIALOG_ACTION.copy()})


@browser_bp.route("/browser/dialog/dismiss", methods=["POST"])
def route_browser_dialog_dismiss():
    """Pre-set the next dialog to be dismissed (cancel). This is the default."""
    _NEXT_DIALOG_ACTION.update({"action": "dismiss", "text": ""})
    return jsonify({"next_action": _NEXT_DIALOG_ACTION.copy()})


# ---------------------------------------------------------------------------
# Navigation history
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/history", methods=["GET"])
def route_browser_history():
    """Return navigation history entries (URL + title) tracked during this session."""
    limit = min(int(request.args.get("limit", 50)), 100)
    entries = list(_NAV_HISTORY)
    return jsonify({"count": len(entries), "entries": entries[-limit:]})


# ---------------------------------------------------------------------------
# Back / Forward / Refresh / Stop
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/back", methods=["POST"])
def route_browser_back():
    """Navigate back in history."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            response = page.go_back(timeout=_clamp_timeout(_json_payload(), "timeout", 10000))
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            _NAV_HISTORY.append({"url": page.url, "title": title})
            return jsonify({
                "status": "back",
                "url": page.url,
                "title": title,
                "navigated": response is not None,
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/forward", methods=["POST"])
def route_browser_forward():
    """Navigate forward in history."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            response = page.go_forward(timeout=_clamp_timeout(_json_payload(), "timeout", 10000))
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            _NAV_HISTORY.append({"url": page.url, "title": title})
            return jsonify({
                "status": "forward",
                "url": page.url,
                "title": title,
                "navigated": response is not None,
            })
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/refresh", methods=["POST"])
def route_browser_refresh():
    """Reload the current page."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.reload(timeout=_clamp_timeout(_json_payload(), "timeout", 15000))
            return jsonify({"status": "refreshed", "url": page.url, "title": page.title()})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/stop", methods=["POST"])
def route_browser_stop():
    """Stop page loading."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.evaluate("() => window.stop()")
            return jsonify({"status": "stopped", "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# URL / Title / Source
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/url", methods=["GET"])
def route_browser_url():
    """Get the current page URL."""
    with _BROWSER_LOCK:
        if _PAGE is None or _PAGE.is_closed():
            return jsonify({"url": None, "open": False})
        return jsonify({"url": _PAGE.url, "open": True})


@browser_bp.route("/browser/title", methods=["GET"])
def route_browser_title():
    """Get the current page title."""
    with _BROWSER_LOCK:
        if _PAGE is None or _PAGE.is_closed():
            return jsonify({"title": None, "open": False})
        try:
            return jsonify({"title": _PAGE.title(), "url": _PAGE.url, "open": True})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/source", methods=["GET"])
def route_browser_source():
    """Get the current page HTML source."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            html = page.content()
            return jsonify({"url": page.url, "html": html, "bytes": len(html)})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/scroll-to", methods=["POST"])
def route_browser_scroll_to():
    """Scroll to a selector or absolute pixel position.

    Provide 'selector' OR 'x'+'y' pixel coords. Optional: 'behavior' smooth|instant.
    """
    data = _json_payload()
    selector = data.get("selector")
    x = data.get("x")
    y = data.get("y")
    behavior = data.get("behavior", "smooth")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            if isinstance(selector, str) and selector:
                page.locator(selector).scroll_into_view_if_needed(timeout=_clamp_timeout(data))
                return jsonify({"scrolled_to": selector, "url": page.url})
            if x is not None or y is not None:
                px = int(x or 0)
                py = int(y or 0)
                page.evaluate(f"window.scrollTo({{left: {px}, top: {py}, behavior: '{behavior}'}})")
                return jsonify({"scrolled_to": {"x": px, "y": py}, "url": page.url})
            return _error("selector or x/y coordinates required")
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/tabs", methods=["GET"])
def route_browser_tabs():
    """List all open tabs. Alias for GET /browser/pages."""
    with _BROWSER_LOCK:
        if _CONTEXT is None:
            return jsonify({"tabs": [], "count": 0})
        pages = _CONTEXT.pages
        active_idx = pages.index(_PAGE) if _PAGE in pages else -1
        tabs = []
        for i, p in enumerate(pages):
            try:
                tabs.append({"index": i, "url": p.url, "title": p.title() or "", "active": i == active_idx})
            except Exception:
                tabs.append({"index": i, "url": "error", "title": "", "active": False})
        return jsonify({"tabs": tabs, "count": len(tabs), "active": active_idx})


@browser_bp.route("/browser/new-tab", methods=["POST"])
def route_browser_new_tab():
    """Open a new tab, optionally navigate to a URL."""
    global _PAGE
    data = _json_payload()
    url = data.get("url")
    with _BROWSER_LOCK:
        if _CONTEXT is None:
            return _error("browser not open — call /browser/navigate first", 409)
        try:
            new_page = _CONTEXT.new_page()
            _setup_page_listeners(new_page)
            _PAGE = new_page
            result = {"status": "opened", "index": _CONTEXT.pages.index(new_page)}
            if isinstance(url, str) and url:
                url_err = _navigation_url_error(url)
                if url_err:
                    return _error(url_err, 403)
                new_page.goto(url, timeout=_clamp_timeout(data, "timeout", 15000))
                result["url"] = new_page.url
                try:
                    result["title"] = new_page.title()
                except Exception:
                    pass
            else:
                result["url"] = new_page.url
            return jsonify(result)
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/close-tab", methods=["POST"])
def route_browser_close_tab():
    """Close a tab by index. Defaults to the active tab. Switches to nearest remaining tab."""
    global _PAGE
    data = _json_payload()
    with _BROWSER_LOCK:
        if _CONTEXT is None:
            return _error("browser not open", 409)
        pages = _CONTEXT.pages
        idx = data.get("index")
        if idx is None:
            target = _PAGE
        else:
            idx = int(idx)
            if idx < 0 or idx >= len(pages):
                return _error(f"tab index {idx} out of range (0-{len(pages)-1})")
            target = pages[idx]
        try:
            closed_url = target.url
            target.close()
            remaining = _CONTEXT.pages
            if remaining:
                _PAGE = remaining[-1]
                return jsonify({"status": "closed", "closed_url": closed_url, "active_url": _PAGE.url})
            _PAGE = None
            return jsonify({"status": "closed", "closed_url": closed_url, "active_url": None})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


@browser_bp.route("/browser/switch-tab", methods=["POST"])
def route_browser_switch_tab():
    """Switch the active tab to a given index."""
    global _PAGE
    data = _json_payload()
    idx = data.get("index")
    if idx is None:
        return _error("index is required")
    idx = int(idx)
    with _BROWSER_LOCK:
        if _CONTEXT is None:
            return _error("browser not open", 409)
        pages = _CONTEXT.pages
        if idx < 0 or idx >= len(pages):
            return _error(f"index {idx} out of range (0-{len(pages)-1})")
        _PAGE = pages[idx]
        return jsonify({"status": "switched", "index": idx, "url": _PAGE.url, "title": _PAGE.title()})


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/viewport", methods=["GET", "POST"])
def route_browser_viewport():
    """GET: return current viewport size. POST: resize viewport (width, height)."""
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            vp = page.viewport_size
            if request.method == "GET":
                return jsonify({"width": vp["width"] if vp else None, "height": vp["height"] if vp else None})
            data = _json_payload()
            w = int(data.get("width", vp["width"] if vp else 1280))
            h = int(data.get("height", vp["height"] if vp else 720))
            page.set_viewport_size({"width": w, "height": h})
            return jsonify({"status": "resized", "width": w, "height": h})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


# ---------------------------------------------------------------------------
# Cookies convenience alias
# ---------------------------------------------------------------------------

@browser_bp.route("/browser/cookies/set", methods=["POST"])
def route_browser_cookies_set():
    """Set cookies directly. cookies: list of cookie objects."""
    data = _json_payload()
    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return _error("cookies (list) is required")
    with _BROWSER_LOCK:
        page, error = _ensure_browser()
        if error:
            return error
        try:
            page.context.add_cookies(cookies)
            return jsonify({"status": "set", "count": len(cookies), "url": page.url})
        except Exception as e:
            return _error(str(e), 500, type=type(e).__name__)


def register_routes(app, state, require_auth):
    app.register_blueprint(browser_bp)
    _wrap_registered_blueprint_routes(app, browser_bp.name, require_auth)
