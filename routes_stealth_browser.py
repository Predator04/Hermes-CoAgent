"""Stealth Browser Engine — undetectable Playwright-based browser automation.

Drop-in module that patches Playwright/Patchright to bypass:
  - Navigator.webdriver detection
  - WebGL fingerprinting
  - Automation feature flags
  - Cloudflare Turnstile / DataDome / Bot detection

Endpoints:
  POST /stealth/open         — Launch undetectable Chromium
  POST /stealth/navigate     — Navigate to URL
  POST /stealth/click        — Click by selector/text/coordinates
  POST /stealth/type         — Type into input
  POST /stealth/extract      — Extract page content
  POST /stealth/screenshot   — Capture page screenshot
  POST /stealth/evaluate     — Run JavaScript
  POST /stealth/wait         — Wait for selector/text
  POST /stealth/close        — Close browser
  GET  /stealth/status       — Browser status + stealth info
  GET  /stealth/health       — Check if browser is detectable
  POST /stealth/profile      — Create persistent profile (bypasses Cloudflare)
"""

import base64
import threading
from importlib import import_module
from pathlib import Path

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import _is_private_url

stealth_bp = Blueprint("stealth", __name__)

_STEALTH_LOCK = threading.RLock()
_PW = None        # Started sync Playwright driver (exposes .chromium)
_PW_NAME = None   # Engine name: "patchright" or "playwright"
_BROWSER = None   # Browser instance
_CONTEXT = None   # Browser context
_PAGE = None      # Active page
_PROFILES_DIR = None
_LAUNCH_ARGS = None


# ── STEALTH PATCHES (inlined — no external deps) ─────────────────

STEALTH_SCRIPTS = {
    # Core: hide webdriver property
    "hide_webdriver": """
        Object.defineProperty(navigator, 'webdriver', {get: () => false});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    """,

    # Chrome runtime (sites check for this)
    "chrome_runtime": """
        window.chrome = {runtime: {}};
        window.chrome.loadTimes = () => {};
        window.chrome.csi = () => {};
        window.chrome.app = {};
    """,

    # Permissions API spoof
    "permissions": """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({state: Notification.permission}) :
                originalQuery(parameters)
        );
    """,

    # WebGL fingerprint randomization
    "webgl_spoof": """
        const getParameterProto = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameterProto.call(this, parameter);
        };
        const getParameterProto2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Intel Inc.';
            if (parameter === 37446) return 'Intel Iris OpenGL Engine';
            return getParameterProto2.call(this, parameter);
        };
    """,

    # Hardware concurrency + device memory
    "hardware_spoof": """
        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
    """,

    # Media codecs (some sites fingerprint via canPlayType)
    "media_codecs": """
        const origCPT = HTMLMediaElement.prototype.canPlayType;
        HTMLMediaElement.prototype.canPlayType = function(type) {
            if (type === 'audio/aac') return 'probably';
            return origCPT.call(this, type);
        };
    """,

    # Remove "HeadlessChrome" from user agent data
    "ua_data": """
        if (navigator.userAgentData) {
            Object.defineProperty(navigator, 'userAgentData', {
                get: () => ({
                    brands: [
                        {brand: 'Google Chrome', version: '131'},
                        {brand: 'Chromium', version: '131'},
                        {brand: 'Not=A?Brand', version: '24'}
                    ],
                    mobile: false,
                    platform: 'Windows'
                })
            });
        }
    """,
}


# Cloudflare Turnstile bypass — inject before page load
CLOUDFLARE_BYPASS_INIT = """
// Remove Cloudflare challenge elements
const observer = new MutationObserver(() => {
    const challenges = document.querySelectorAll('[id*="challenge"], [class*="challenge"], #turnstile-wrapper, .cf-turnstile, #cf-challenge');
    challenges.forEach(el => el.remove());
});
observer.observe(document.documentElement, {childList: true, subtree: true});
"""


# Chromium launch args for maximum stealth
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-site-isolation-trials",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-accelerated-2d-canvas",
    "--no-first-run",
    "--no-zygote",
    "--disable-gpu",
    "--hide-scrollbars",
    "--mute-audio",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-print-preview",
    "--disable-speech-api",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--password-store=basic",
    "--use-mock-keychain",
    # Window size — real desktop resolution
    "--window-size=1920,1080",
    "--window-position=0,0",
]


# ── helpers ──────────────────────────────────────────────────────

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


def _load_playwright():
    """Load Patchright first (stealth-patched), fall back to Playwright.

    Returns a *started* sync Playwright driver — the object that exposes
    ``.chromium``. The top-level package (``import patchright``) only carries a
    docstring and has no ``.chromium`` attribute, so we must go through the
    sync API: ``sync_api.sync_playwright().start()``.
    """
    global _PW, _PW_NAME
    if _PW:
        return _PW

    for name in ["patchright", "playwright"]:
        try:
            sync_api = import_module(f"{name}.sync_api")
            pw = sync_api.sync_playwright().start()
            _PW = pw
            _PW_NAME = name
            return pw
        except (ImportError, AttributeError):
            continue

    raise RuntimeError(
        "Neither patchright nor playwright installed. "
        "pip install patchright  (recommended — includes stealth patches)\n"
        "OR: pip install playwright && playwright install chromium"
    )


def _ensure_browser(new_page: bool = False, profile: str = None):
    """Get or create browser page. Creates browser if needed."""
    global _BROWSER, _CONTEXT, _PAGE, _PROFILES_DIR

    pw = _load_playwright()

    if _BROWSER is None or not _BROWSER.is_connected():
        # Also skip if we have a persistent context already alive
        has_persistent = _CONTEXT is not None and _PAGE is not None and not _PAGE.is_closed()
        if has_persistent and not new_page:
            return _PAGE

        # Set up profiles dir for persistent sessions
        if not _PROFILES_DIR:
            _PROFILES_DIR = Path.home() / "Hermes CoAgent" / "stealth_profiles"
            _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

        if profile:
            if not _safe_profile_name(profile):
                raise ValueError(f"Invalid profile name: {profile}")
            profile_dir = _PROFILES_DIR / profile
            profile_dir.mkdir(parents=True, exist_ok=True)
            _CONTEXT = pw.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                args=STEALTH_LAUNCH_ARGS,
                viewport={"width": 1920, "height": 1080},
            )
            _PAGE = _CONTEXT.pages[0] if _CONTEXT.pages else _CONTEXT.new_page()
        else:
            _BROWSER = pw.chromium.launch(
                headless=False,
                args=STEALTH_LAUNCH_ARGS,
            )
            _CONTEXT = _BROWSER.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            _PAGE = _CONTEXT.new_page()

        # Inject all stealth scripts before any page loads
        _inject_stealth(_PAGE)

    if new_page and _PAGE:
        _PAGE = _CONTEXT.new_page()
        _inject_stealth(_PAGE)

    return _PAGE


def _inject_stealth(page):
    """Inject all stealth patches into a page before it loads."""
    for name, script in STEALTH_SCRIPTS.items():
        page.add_init_script(script)
    page.add_init_script(CLOUDFLARE_BYPASS_INIT)


def _safe_profile_name(name: str) -> bool:
    """Reject path traversal in profile names."""
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    if len(name) > 64:
        return False
    return bool(__import__("re").match(r"^[A-Za-z0-9_-]+$", name))


def _current_status() -> dict:
    return {
        "browser_open": _BROWSER is not None and (_BROWSER.is_connected() if _BROWSER else False),
        "page_loaded": _PAGE is not None,
        "page_url": _PAGE.url if _PAGE else None,
        "profiles_dir": str(_PROFILES_DIR) if _PROFILES_DIR else None,
        "stealth_scripts": list(STEALTH_SCRIPTS.keys()),
        "launch_args_count": len(STEALTH_LAUNCH_ARGS),
        "engine": _PW_NAME or "playwright",
    }


# ── endpoints ────────────────────────────────────────────────────

@stealth_bp.route("/stealth", methods=["GET"])
def route_stealth_index():
    return jsonify({
        "engine": "Stealth Browser",
        "endpoints": [
            {"path": "/stealth/open", "method": "POST", "desc": "Launch undetectable browser"},
            {"path": "/stealth/navigate", "method": "POST", "desc": "Navigate to URL"},
            {"path": "/stealth/click", "method": "POST", "desc": "Click by selector/text/coords"},
            {"path": "/stealth/type", "method": "POST", "desc": "Type into input field"},
            {"path": "/stealth/extract", "method": "POST", "desc": "Extract page content"},
            {"path": "/stealth/screenshot", "method": "POST", "desc": "Capture page screenshot"},
            {"path": "/stealth/evaluate", "method": "POST", "desc": "Run JavaScript in page"},
            {"path": "/stealth/wait", "method": "POST", "desc": "Wait for selector/text"},
            {"path": "/stealth/close", "method": "POST", "desc": "Close browser"},
            {"path": "/stealth/status", "method": "GET", "desc": "Browser status"},
            {"path": "/stealth/health", "method": "GET", "desc": "Check detectability"},
            {"path": "/stealth/profile", "method": "POST", "desc": "Create persistent profile"},
        ],
        "features": [
            "Navigator.webdriver = false",
            "WebGL fingerprint randomization",
            "Chrome runtime API spoofing",
            "Automation flags removed",
            "Hardware concurrency spoofed",
            "Cloudflare Turnstile bypass",
            "Persistent browser profiles",
        ],
    })


@stealth_bp.route("/stealth/status", methods=["GET"])
def route_stealth_status():
    return jsonify(_current_status())


@stealth_bp.route("/stealth/open", methods=["POST"])
def route_stealth_open():
    """Launch a fresh undetectable browser."""
    payload = _json_payload()
    profile = payload.get("profile", None)

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser(new_page=True, profile=profile)
            return jsonify({
                "status": "opened",
                "url": page.url,
                "engine": _PW_NAME or "playwright",
                "stealth_scripts_injected": len(STEALTH_SCRIPTS),
                "profile": profile,
            })
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/navigate", methods=["POST"])
def route_stealth_navigate():
    """Navigate to URL with full stealth."""
    payload = _json_payload()
    url = (payload.get("url") or "").strip()
    if not url:
        return _error("Missing 'url'")

    if _is_private_url(url):
        return _error(f"URL not allowed: {url}", status=403)

    wait_until = payload.get("wait_until", "domcontentloaded")
    timeout = int(payload.get("timeout", 30000))

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()
            page.goto(url, wait_until=wait_until, timeout=timeout)

            # Run cloudflare detection check
            cf_detected = page.evaluate("""
                (() => {
                    const title = document.title || '';
                    const body = document.body ? document.body.innerText.substring(0, 500) : '';
                    const blocked = title.includes('Just a moment') ||
                                    title.includes('Checking your browser') ||
                                    title.includes('Attention Required') ||
                                    body.includes('Cloudflare') ||
                                    body.includes('DDoS protection') ||
                                    !!document.querySelector('#cf-challenge') ||
                                    !!document.querySelector('.cf-browser-verification');
                    return blocked;
                })()
            """)

            return jsonify({
                "status": "navigated",
                "url": page.url,
                "title": page.title(),
                "cloudflare_blocked": cf_detected,
                "stealth_ok": not cf_detected,
            })
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/click", methods=["POST"])
def route_stealth_click():
    """Click by CSS selector, text content, or coordinates."""
    payload = _json_payload()
    selector = payload.get("selector")
    text = payload.get("text")
    x = payload.get("x")
    y = payload.get("y")

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()

            if selector:
                page.click(selector)
            elif text:
                page.click(f"text={text}")
            elif x is not None and y is not None:
                page.mouse.click(x, y)
            else:
                return _error("Need 'selector', 'text', or 'x'+'y'")

            return jsonify({"status": "clicked"})
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/type", methods=["POST"])
def route_stealth_type():
    """Type text into a field."""
    payload = _json_payload()
    selector = payload.get("selector", "input, textarea, [contenteditable]")
    text = payload.get("text", "")
    delay = int(payload.get("delay", 50))  # ms between keystrokes — human-like

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()
            page.fill(selector, "")  # Clear
            page.type(selector, text, delay=delay)
            return jsonify({"status": "typed", "chars": len(text)})
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/extract", methods=["POST"])
def route_stealth_extract():
    """Extract page content — full text, links, or custom selector."""
    payload = _json_payload()
    mode = payload.get("mode", "text")  # text | links | html | selector
    selector = payload.get("selector")
    limit = int(payload.get("limit", 5000))

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()

            if mode == "text":
                content = page.evaluate("() => document.body ? document.body.innerText : ''")
                if len(content) > limit:
                    content = content[:limit] + f"\n\n... [truncated at {limit} chars]"
                return jsonify({"mode": "text", "content": content, "length": len(content)})

            elif mode == "links":
                links = page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                        text: a.innerText.trim().substring(0, 200),
                        href: a.href
                    })).slice(0, %d)
                """ % min(limit, 200))
                return jsonify({"mode": "links", "links": links, "count": len(links)})

            elif mode == "html":
                content = page.content()
                if len(content) > limit:
                    content = content[:limit] + "\n\n... [truncated]"
                return jsonify({"mode": "html", "content": content, "length": len(content)})

            elif mode == "selector" and selector:
                # SAFE: pass selector as Playwright arg, never interpolate into JS
                elements = page.evaluate(
                    "(sel) => Array.from(document.querySelectorAll(sel)).map(el => el.innerText.trim()).filter(t => t).slice(0, 50)",
                    selector
                )
                elements = elements[:min(limit, 50)]
                return jsonify({"mode": "selector", "selector": selector, "results": elements, "count": len(elements)})

            else:
                return _error(f"Unknown mode: {mode}")

        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/screenshot", methods=["POST"])
def route_stealth_screenshot():
    """Capture browser page screenshot."""
    payload = _json_payload()
    full_page = payload.get("full_page", False)

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()
            screenshot_bytes = page.screenshot(full_page=full_page, type="png")
            b64 = base64.b64encode(screenshot_bytes).decode()
            return jsonify({
                "status": "captured",
                "format": "png",
                "size_bytes": len(screenshot_bytes),
                "data": b64,
            })
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/evaluate", methods=["POST"])
def route_stealth_evaluate():
    """Run arbitrary JavaScript in the page."""
    payload = _json_payload()
    script = payload.get("script", "").strip()
    if not script:
        return _error("Missing 'script'")

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()
            result = page.evaluate(script)
            return jsonify({"status": "evaluated", "result": result})
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/wait", methods=["POST"])
def route_stealth_wait():
    """Wait for selector or text to appear."""
    payload = _json_payload()
    selector = payload.get("selector")
    text = payload.get("text")
    timeout = int(payload.get("timeout", 15000))

    with _STEALTH_LOCK:
        try:
            page = _ensure_browser()
            if selector:
                page.wait_for_selector(selector, timeout=timeout)
                return jsonify({"status": "found", "selector": selector})
            elif text:
                page.wait_for_selector(f"text={text}", timeout=timeout)
                return jsonify({"status": "found", "text": text})
            else:
                return _error("Need 'selector' or 'text'")
        except Exception as e:
            return _error(str(e), status=500)


@stealth_bp.route("/stealth/close", methods=["POST"])
def route_stealth_close():
    """Close the stealth browser."""
    global _BROWSER, _CONTEXT, _PAGE

    with _STEALTH_LOCK:
        try:
            if _PAGE and not _PAGE.is_closed():
                _PAGE.close()
            if _CONTEXT:
                _CONTEXT.close()
            if _BROWSER and _BROWSER.is_connected():
                _BROWSER.close()
        except Exception:
            pass
        finally:
            _BROWSER = None
            _CONTEXT = None
            _PAGE = None

    return jsonify({"status": "closed"})


@stealth_bp.route("/stealth/health", methods=["GET"])
def route_stealth_health():
    """Check if the stealth browser is detectable using common fingerprint tests."""
    with _STEALTH_LOCK:
        try:
            page = _ensure_browser(new_page=True)  # fresh tab, don't destroy user's session
            page.goto("about:blank", timeout=5000)

            checks = page.evaluate("""
                (() => {
                    // Test 1: navigator.webdriver
                    const webdriver = navigator.webdriver;
                    
                    // Test 2: Chrome runtime
                    const hasChromeRuntime = typeof window.chrome !== 'undefined' && 
                                             typeof window.chrome.runtime !== 'undefined';
                    
                    // Test 3: Plugins array
                    const pluginsLength = navigator.plugins ? navigator.plugins.length : 'undefined';
                    
                    // Test 4: Languages
                    const languages = navigator.languages;
                    
                    // Test 5: Permissions (check if query exists)
                    const hasPermissions = typeof navigator.permissions !== 'undefined' && 
                                           typeof navigator.permissions.query !== 'undefined';
                    
                    // Test 6: WebGL vendor
                    let webglVendor = 'none';
                    try {
                        const canvas = document.createElement('canvas');
                        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                        if (gl) {
                            const dbg = gl.getExtension('WEBGL_debug_renderer_info');
                            webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : 'no_debug_info';
                        }
                    } catch(e) { webglVendor = 'error'; }
                    
                    // Test 7: Hardware concurrency
                    const hw = navigator.hardwareConcurrency;
                    
                    // Test 8: User agent
                    const ua = navigator.userAgent;
                    const hasHeadless = ua.includes('Headless');
                    
                    return {
                        webdriver: webdriver,
                        webdriver_ok: webdriver === false || webdriver === undefined,
                        has_chrome_runtime: hasChromeRuntime,
                        plugins_length: pluginsLength,
                        languages: languages,
                        has_permissions: hasPermissions,
                        webgl_vendor: webglVendor,
                        hardware_concurrency: hw,
                        has_headless_in_ua: hasHeadless,
                        stealth_score: (
                            (webdriver === false || webdriver === undefined ? 1 : 0) +
                            (hasChromeRuntime ? 1 : 0) +
                            (pluginsLength > 0 ? 1 : 0) +
                            (hasPermissions ? 1 : 0) +
                            (webglVendor !== 'Google Inc.' ? 1 : 0) +
                            (!hasHeadless ? 1 : 0)
                        )
                    };
                })()
            """)

            checks["stealth_score_max"] = 6
            checks["verdict"] = (
                "STEALTH" if checks.get("stealth_score", 0) >= 4
                else "SUSPICIOUS" if checks.get("stealth_score", 0) >= 2
                else "DETECTABLE"
            )
            return jsonify(checks)

        except Exception as e:
            return jsonify({"error": str(e), "verdict": "UNKNOWN"})


@stealth_bp.route("/stealth/profile", methods=["POST"])
def route_stealth_profile():
    """Create/manage a persistent browser profile for Cloudflare-resistant sessions."""
    payload = _json_payload()
    action = payload.get("action", "create")  # create | list | delete
    name = payload.get("name", "default")

    if not _safe_profile_name(name):
        return _error(f"Invalid profile name: {name}. Use only A-Z, a-z, 0-9, _, - (max 64 chars)", status=400)

    global _PROFILES_DIR

    if not _PROFILES_DIR:
        _PROFILES_DIR = Path.home() / "Hermes CoAgent" / "stealth_profiles"
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    if action == "list":
        profiles = [d.name for d in _PROFILES_DIR.iterdir() if d.is_dir()]
        return jsonify({"action": "list", "profiles": profiles, "dir": str(_PROFILES_DIR)})

    if action == "create":
        profile_dir = _PROFILES_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Open with this profile to initialize it
        with _STEALTH_LOCK:
            try:
                page = _ensure_browser(profile=name)
                page.goto("about:blank")
                return jsonify({
                    "action": "created",
                    "profile": name,
                    "dir": str(profile_dir),
                    "note": "Persistent profile survives browser restarts. Good for Cloudflare-resistant sessions.",
                })
            except Exception as e:
                return _error(str(e), status=500)

    if action == "delete":
        profile_dir = _PROFILES_DIR / name
        if profile_dir.exists():
            import shutil
            shutil.rmtree(profile_dir)
            return jsonify({"action": "deleted", "profile": name})
        return _error(f"Profile '{name}' not found", status=404)

    return _error(f"Unknown action: {action}")


def register_routes(app, state, require_auth):
    """Register stealth browser routes on the Flask app."""
    _auth_blueprint(stealth_bp, require_auth)
    app.register_blueprint(stealth_bp)
