"""
Store Setup Wizard — Automated Shopify store configuration via desktop automation.
Walks through: app credentials → plan → DSers install → password removal.
Trigger from CoAgent: POST /store/setup/run
"""

import json, logging, time, re
from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)
setup_bp = Blueprint("setup", __name__)

# ── Keyboard / navigation helpers ────────────────────────────────

def _powershell(state, script: str) -> dict:
    """Execute a PowerShell script via CoAgent's COM toolkit."""
    import urllib.request
    token = state.get("auth_token", "")
    url = f"http://127.0.0.1:{state.get('port', 9123)}/com/powershell"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"script": script}).encode()
    try:
        resp = urllib.request.urlopen(req, data=body, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _vision(state):
    """Get current screen state."""
    import urllib.request
    token = state.get("auth_token", "")
    url = f"http://127.0.0.1:{state.get('port', 9123)}/vision/describe"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, data=b"{}", timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _find_window(state, title_contains: str):
    """Find a window handle by title substring using EnumWindows."""
    # Escape for safe PowerShell string interpolation: double any embedded single quotes
    safe_title = title_contains.replace("'", "''")
    ps = f"""
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class W32 {{
        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);
        public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
        [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }}
    "@;
    $callback = {{
        param($hWnd, $lParam)
        $sb = New-Object Text.StringBuilder 256
        [W32]::GetWindowText($hWnd, $sb, 256)
        $t = $sb.ToString()
        if ($t.Contains('{safe_title}')) {{
            Write-Host "HWND:$hWnd"
            return $false
        }}
        return $true
    }};
    [W32]::EnumWindows($callback, 0);
    """
    return _powershell(state, ps)


def _focus_and_type(state, url: str):
    """Open a URL in Brave and focus the window."""
    # Open new tab — escape double quotes for safe PowerShell interpolation
    safe_url = url.replace('"', '""')
    ps = f"""Start-Process brave.exe -ArgumentList '"{safe_url}"' """
    _powershell(state, ps)
    time.sleep(4)
    return True


def _type_text(state, text: str):
    """Type text via keyboard simulation."""
    # Escape special chars for SendKeys
    safe = text.replace("{", "{{").replace("}", "}}")
    safe = safe.replace("+", "{+}").replace("^", "{^}").replace("%", "{%}")
    safe = safe.replace("~", "{~}").replace("(", "{(}").replace(")", "{)}")
    ps = f"""
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("{safe}")
    """
    return _powershell(state, ps)


def _send_keys(state, keys: str):
    """Send raw keys (Ctrl+L, Tab, Enter, etc.)."""
    ps = f"""
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("{keys}")
    """
    return _powershell(state, ps)


# ── Step: Navigate to Develop Apps page ─────────────────────────

def _step_develop_apps(state) -> dict:
    """Navigate to the Develop Apps page in the active Brave window."""
    log.info("Step 1: Navigate to Develop Apps")
    _focus_and_type(state, "https://admin.shopify.com/store/m5ng7s-s7/settings/apps/develop-apps")
    time.sleep(5)
    
    # Focus the Brave window with Shopify
    result = _find_window(state, "Shopify")
    if result.get("ok") and result.get("result", {}).get("stdout", ""):
        hwnd_line = [l for l in result["result"]["stdout"].split("\n") if l.startswith("HWND:")]
        if hwnd_line:
            hwnd = hwnd_line[0].split(":")[1].strip()
            # Focus it
            focus_ps = f"""
            Add-Type @"
            using System; using System.Runtime.InteropServices;
            public class W32 {{ [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); }}
            "@;
            [W32]::ShowWindow({hwnd}, 9) | Out-Null
            Start-Sleep 1
            [W32]::SetForegroundWindow({hwnd}) | Out-Null
            Write-Host "Focused"
            """
            _powershell(state, focus_ps)
    time.sleep(3)
    return {"ok": True, "step": "develop_apps"}


# ── Step: Get Client Secret from the app page ───────────────────

def _step_get_client_secret(state) -> dict:
    """Navigate to the Store Sync app's API credentials page and extract the secret."""
    log.info("Step 2: Get Client Secret")
    
    # Navigate to the Store Sync app's API credentials
    app_url = "https://admin.shopify.com/store/m5ng7s-s7/settings/apps/224861802"
    _focus_and_type(state, app_url)
    time.sleep(5)
    
    # Try to scroll and look for the secret - use keyboard
    # Tab to find the "Reveal" or "Copy" button for the secret
    _send_keys(state, "{TAB 20}")
    time.sleep(2)
    
    # Take vision snapshot
    vision = _vision(state)
    ocr_text = vision.get("ocr", {}).get("text", "")
    log.info(f"OCR found {len(ocr_text)} chars")
    
    # Check if we can see "client secret" or "API secret" in OCR
    secret_found = None
    for line in ocr_text.split("\n"):
        if "shp_" in line.lower() or "secret" in line.lower():
            # Extract potential secret
            matches = re.findall(r'shp_[a-zA-Z0-9]+', line)
            if matches:
                secret_found = matches[0]
                break
    
    return {
        "ok": True,
        "step": "get_client_secret",
        "secret_found": secret_found,
        "ocr_preview": ocr_text[:500]
    }


# ── Step: Navigate to Plan page ─────────────────────────────────

def _step_navigate_plan(state) -> dict:
    """Navigate to the Plan settings page."""
    log.info("Step 3: Navigate to Plan page")
    _focus_and_type(state, "https://admin.shopify.com/store/m5ng7s-s7/settings/plan")
    time.sleep(5)
    return {"ok": True, "step": "plan_page"}


# ── Step: Install DSers ─────────────────────────────────────────

def _step_install_dsers(state) -> dict:
    """Navigate to DSers app page in the App Store."""
    log.info("Step 4: Install DSers")
    _focus_and_type(state, "https://apps.shopify.com/dsers")
    time.sleep(5)
    
    # Try to find and click "Add app" or "Install" button
    # Tab through to find it
    _send_keys(state, "{TAB 30}")
    time.sleep(2)
    
    # Try clicking "Add" via Tab+Enter approach
    # Sometimes the install button is focused via tab
    _send_keys(state, "{ENTER}")
    time.sleep(3)
    
    return {"ok": True, "step": "install_dsers"}


# ── Step: Remove password ───────────────────────────────────────

def _step_remove_password(state) -> dict:
    """Navigate to password settings and disable."""
    log.info("Step 5: Remove password page")
    _focus_and_type(state, "https://admin.shopify.com/store/m5ng7s-s7/settings/online-store")
    time.sleep(5)
    
    # Tab to the password toggle/disable button
    _send_keys(state, "{TAB 15}")
    time.sleep(1)
    _send_keys(state, "{ENTER}")
    time.sleep(2)
    
    return {"ok": True, "step": "remove_password"}


# ── Main setup flow ─────────────────────────────────────────────

@setup_bp.route("/store/setup/run", methods=["POST"])
def run_setup():
    """Run the full store setup wizard."""
    body = request.get_json(silent=True) or {}
    steps = body.get("steps", ["all"])
    
    state = {
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }
    
    available_steps = {
        "develop_apps": _step_develop_apps,
        "get_secret": _step_get_client_secret,
        "plan": _step_navigate_plan,
        "dsers": _step_install_dsers,
        "password": _step_remove_password,
    }
    
    if "all" in steps:
        steps = list(available_steps.keys())
    
    results = {}
    for step_name in steps:
        if step_name not in available_steps:
            results[step_name] = {"ok": False, "error": "Unknown step"}
            continue
        try:
            results[step_name] = available_steps[step_name](state)
        except Exception as e:
            results[step_name] = {"ok": False, "error": str(e)}
    
    return jsonify({"ok": True, "results": results})


# ── Single-step endpoints ───────────────────────────────────────

@setup_bp.route("/store/setup/develop-apps", methods=["POST"])
def develop_apps():
    return jsonify(_step_develop_apps({
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }))


@setup_bp.route("/store/setup/get-secret", methods=["POST"])
def get_secret():
    return jsonify(_step_get_client_secret({
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }))


@setup_bp.route("/store/setup/plan", methods=["POST"])
def plan_page():
    return jsonify(_step_navigate_plan({
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }))


@setup_bp.route("/store/setup/dsers", methods=["POST"])
def install_dsers():
    return jsonify(_step_install_dsers({
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }))


@setup_bp.route("/store/setup/password", methods=["POST"])
def remove_password():
    return jsonify(_step_remove_password({
        "auth_token": request.headers.get("Authorization", "").replace("Bearer ", ""),
        "port": 9123,
    }))


# ── Registration ────────────────────────────────────────────────

def register_routes(app, app_state, require_auth):
    app.register_blueprint(setup_bp)
    log.info("[setup] routes registered (6 endpoints)")
