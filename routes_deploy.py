"""One-Click Deploy — install CoAgent on a fresh Windows machine from scratch.

Endpoints:
  POST /deploy/install     — Install pip + Python deps
  POST /deploy/oneclick    — Full pipeline: deps → token → launch
  POST /deploy/tunnel      — Optional ngrok tunnel (explains when needed)
  GET  /deploy/status      — Live status + ngrok explanation
  GET  /deploy/script      — Download standalone oneclick_deploy.ps1
"""

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, Response

from routes_bypass import _json_payload

try:
    from routes_ngrok import ensure_ngrok as _ensure_ngrok
except ImportError:
    _ensure_ngrok = None

deploy_bp = Blueprint("deploy", __name__)

_DEPLOY_LOCK = threading.Lock()
_DEPLOY_STATE = {
    "phase": "idle",       # idle | installing | launching | tunnelling | done | error
    "started": None,
    "finished": None,
    "step": "",
    "log": [],
    "token": None,
    "token_preview": None,
    "port": 9123,
    "lan_url": None,
    "ngrok_url": None,
    "error": None,
    "coagent_pid": None,
    "ngrok_pid": None,
}


# ── helpers ──────────────────────────────────────────────────────

def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    with _DEPLOY_LOCK:
        _DEPLOY_STATE["log"].append(f"[{ts}] {msg}")
        _DEPLOY_STATE["step"] = msg


def _find_python() -> str | None:
    """Find a working Python 3.10+ on the system."""
    candidates = []
    for name in ["python", "python3", "py"]:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    # Also check common install dirs
    for base in [r"C:\Program Files",
                 os.path.expanduser(r"~\AppData\Local\Programs")]:
        for d in Path(base).glob("Python3*"):
            exe = d / "python.exe"
            if exe.exists():
                candidates.append(str(exe))

    for exe in candidates:
        try:
            r = subprocess.run(
                [exe, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                ver = tuple(map(int, r.stdout.strip().lstrip("(").rstrip(")").split(",")))
                if ver >= (3, 10):
                    return exe
        except Exception:
            continue
    return None


def _run(cmd: list, timeout: int = 120, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def _pip_install(python: str, packages: list[str]) -> bool:
    """Install pip packages. Returns True on success."""
    _log(f"Installing: {', '.join(packages[:6])}{'...' if len(packages) > 6 else ''}")
    reqs = [
        "flask", "waitress", "pillow", "pyautogui", "pywinauto",
        "pytesseract", "pygetwindow", "pyperclip", "pystray",
        "requests", "mss", "psutil",
    ]
    if packages:
        reqs.extend(packages)

    # First ensure pip itself
    try:
        pip_check = _run([python, "-m", "pip", "--version"], timeout=15)
    except Exception:
        pip_check = None
    if pip_check is None or pip_check.returncode != 0:
        _log("Installing pip...")
        _run([python, "-m", "ensurepip", "--default-pip"], timeout=60)

    for pkg in reqs:
        _log(f"  pip install {pkg}")
        r = _run([python, "-m", "pip", "install", "--quiet", pkg], timeout=120)
        if r.returncode != 0:
            # Try without quiet to see errors
            r2 = _run([python, "-m", "pip", "install", pkg], timeout=120)
            if r2.returncode != 0:
                _log(f"  WARNING: {pkg} install returned code {r2.returncode}")
                return False
    return True


# ── TUNNEL EXPLANATION (shown in status and tunnel endpoint) ─────

TUNNEL_EXPLANATION = """
🔒 **When you need a tunnel (ngrok):**
• You're on **T-Mobile/cellular** — carriers block inbound connections
• You're behind **double NAT** (apartment WiFi, shared network)
• You're on a **corporate/guest network** that blocks LAN access
• You need to reach CoAgent from **outside your home network**

🏠 **When you DON'T need a tunnel:**
• You're on your **home WiFi/LAN** — direct IP access works
• Hermes (WSL) and CoAgent (Windows) are on the **same machine**
• You're accessing from another device on the **same LAN**

⚠️  **Security note:** A tunnel exposes CoAgent to the internet.
    Always use --secure (token auth) when using a tunnel.
"""


# ── endpoints ────────────────────────────────────────────────────

@deploy_bp.route("/deploy", methods=["GET"])
def route_deploy_index():
    return jsonify({
        "endpoints": [
            {"path": "/deploy/install", "method": "POST", "desc": "Install Python deps"},
            {"path": "/deploy/oneclick", "method": "POST", "desc": "Full pipeline: deps → token → launch"},
            {"path": "/deploy/tunnel", "method": "POST", "desc": "Start/stop optional ngrok tunnel"},
            {"path": "/deploy/status", "method": "GET", "desc": "Live status + tunnel explanation"},
            {"path": "/deploy/script", "method": "GET", "desc": "Download standalone deploy script"},
        ]
    })


@deploy_bp.route("/deploy/status", methods=["GET"])
def route_deploy_status():
    """Live status of current/last deploy run + ngrok explanation."""
    with _DEPLOY_LOCK:
        state = dict(_DEPLOY_STATE)
        state["log"] = list(_DEPLOY_STATE["log"])
    return jsonify({
        "phase": state["phase"],
        "step": state["step"],
        "started": state["started"],
        "finished": state["finished"],
        "port": state["port"],
        "lan_url": state["lan_url"],
        "ngrok_url": state["ngrok_url"],
        "token": state["token_preview"] or (state["token"][:8] + "..." if state["token"] else None),
        "log": state["log"][-30:],
        "coagent_pid": state.get("coagent_pid"),
        "ngrok_pid": state.get("ngrok_pid"),
        "tunnel_explanation": TUNNEL_EXPLANATION.strip(),
    })


@deploy_bp.route("/deploy/install", methods=["POST"])
def route_deploy_install():
    """Install Python dependencies only."""
    with _DEPLOY_LOCK:
        if _DEPLOY_STATE["phase"] not in ("idle", "done", "error"):
            return _error(f"Deploy already in phase: {_DEPLOY_STATE['phase']}", status=409)

        _DEPLOY_STATE["phase"] = "installing"
        _DEPLOY_STATE["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _DEPLOY_STATE["log"] = []
        _DEPLOY_STATE["error"] = None

    python = _find_python()
    if not python:
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "error"
            _DEPLOY_STATE["error"] = "No Python 3.10+ found. Install from python.org"
        return _error(_DEPLOY_STATE["error"], status=500)

    _log(f"Using Python: {python}")

    try:
        ok = _pip_install(python, [])
        if not ok:
            with _DEPLOY_LOCK:
                _DEPLOY_STATE["phase"] = "error"
                _DEPLOY_STATE["error"] = "pip install failed — check logs"
            return _error("pip install failed", status=500)
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "done"
            _DEPLOY_STATE["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return jsonify({"status": "ok", "phase": "done", "log": _DEPLOY_STATE["log"][-10:]})
    except Exception as e:
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "error"
            _DEPLOY_STATE["error"] = str(e)
        return _error(str(e), status=500)


@deploy_bp.route("/deploy/oneclick", methods=["POST"])
def route_deploy_oneclick():
    """Full one-click pipeline: deps → token → launch."""
    payload = _json_payload()
    try:
        port = int(payload.get("port", 9123))
    except (TypeError, ValueError):
        return _error("port must be an integer", status=400)
    if not (1 <= port <= 65535):
        return _error("port must be between 1 and 65535", status=400)
    _tunnel = payload.get("tunnel", False)
    tunnel = _tunnel is True or str(_tunnel).strip().lower() in ("true", "1", "yes", "on")

    with _DEPLOY_LOCK:
        if _DEPLOY_STATE["phase"] not in ("idle", "done", "error"):
            return _error(f"Deploy already in phase: {_DEPLOY_STATE['phase']}", status=409)

        _DEPLOY_STATE["phase"] = "installing"
        _DEPLOY_STATE["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _DEPLOY_STATE["log"] = []
        _DEPLOY_STATE["error"] = None
        _DEPLOY_STATE["port"] = port

    python = _find_python()
    if not python:
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "error"
            _DEPLOY_STATE["error"] = "No Python 3.10+ found"
        return _error(_DEPLOY_STATE["error"], status=500)

    _log(f"Python: {python}")

    # Step 1: Install deps
    try:
        ok = _pip_install(python, ["patchright"])
        if not ok:
            with _DEPLOY_LOCK:
                _DEPLOY_STATE["phase"] = "error"
                _DEPLOY_STATE["error"] = "pip install failed — check logs"
            return _error("pip install failed", status=500)
    except Exception as e:
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "error"
            _DEPLOY_STATE["error"] = f"Deps failed: {e}"
        return _error(str(e), status=500)

    # Step 2: Generate token
    token = secrets.token_hex(32)
    _log(f"Token: {token[:8]}...")

    # Step 3: Start CoAgent
    coagent_dir = Path.cwd()
    _DEPLOY_STATE["phase"] = "launching"
    _log(f"Launching CoAgent from {coagent_dir}")

    try:
        proc = subprocess.Popen(
            [python, "-B", str(coagent_dir / "hermes_coagent.py"),
             "--secure", f"--token={token}", "--allow-external", f"--port={port}"],
            cwd=str(coagent_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _DEPLOY_STATE["coagent_pid"] = proc.pid
        time.sleep(3)

        # Verify it's up
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=10):
                pass
            _log("CoAgent is running!")
        except Exception:
            _log("Waiting for CoAgent to start...")
            time.sleep(5)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=10):
                    pass
                _log("CoAgent is running!")
            except Exception as e2:
                _log(f"CoAgent may still be starting: {e2}")

        lan_url = f"http://127.0.0.1:{port}"
        _DEPLOY_STATE["lan_url"] = lan_url
        _DEPLOY_STATE["token"] = token
        _DEPLOY_STATE["token_preview"] = token[:8] + "..."

        # Step 4: Optional ngrok
        ngrok_url = None
        if tunnel:
            _DEPLOY_STATE["phase"] = "tunnelling"
            ngrok = shutil.which("ngrok") or shutil.which("ngrok.exe")
            if not ngrok and _ensure_ngrok is not None:
                _log("ngrok missing - auto-installing...")
                res = _ensure_ngrok(auth_token=payload.get("ngrok_authtoken"))
                if res.get("ok"):
                    ngrok = res.get("path")
                    if res.get("downloaded"):
                        _log(f"ngrok installed at {ngrok}")
                else:
                    _log(f"ngrok auto-install failed: {res.get('error')}")
            if ngrok:
                _log("Starting ngrok tunnel...")
                ngrok_proc = subprocess.Popen(
                    [ngrok, "http", str(port), "--log=stdout"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                _DEPLOY_STATE["ngrok_pid"] = ngrok_proc.pid
                time.sleep(3)
                try:
                    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=10) as resp:
                        data = json.loads(resp.read())
                    for t in data.get("tunnels", []):
                        if t.get("proto") == "https":
                            ngrok_url = t["public_url"]
                            _DEPLOY_STATE["ngrok_url"] = ngrok_url
                            _log(f"Ngrok: {ngrok_url}")
                            break
                except Exception:
                    _log("Ngrok started but couldn't fetch URL (may need auth)")
            else:
                _log("WARNING: ngrok not found. Install from ngrok.com")

        _DEPLOY_STATE["phase"] = "done"
        _DEPLOY_STATE["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        return jsonify({
            "status": "ok",
            "lan_url": lan_url,
            "ngrok_url": ngrok_url,
            "token_preview": token[:8] + "...",
            "port": port,
            "phase": "done",
            "tunnel_note": "Tunnel was not requested (use POST /deploy/tunnel to add one)" if not tunnel else None,
        })

    except Exception as e:
        with _DEPLOY_LOCK:
            _DEPLOY_STATE["phase"] = "error"
            _DEPLOY_STATE["error"] = str(e)
        return _error(str(e), status=500)


@deploy_bp.route("/deploy/tunnel", methods=["POST"])
def route_deploy_tunnel():
    """Start or stop optional ngrok tunnel. Explains when you need it."""
    payload = _json_payload()
    action = payload.get("action", "start")  # start | stop | status

    ngrok = shutil.which("ngrok") or shutil.which("ngrok.exe")

    if action == "status":
        tunnel_active = False
        tunnel_url = _DEPLOY_STATE["ngrok_url"]
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=5) as resp:
                data = json.loads(resp.read())
            for t in data.get("tunnels", []):
                if t.get("proto") == "https":
                    tunnel_active = True
                    tunnel_url = t["public_url"]
                    break
        except Exception:
            tunnel_active = False

        return jsonify({
            "active": tunnel_active,
            "url": tunnel_url,
            "ngrok_installed": bool(ngrok),
            "explanation": {
                "when_needed": [
                    "T-Mobile/cellular connections — carriers block inbound",
                    "Behind double NAT (apartment WiFi, shared networks)",
                    "Corporate/guest networks blocking LAN access",
                    "Accessing CoAgent from outside your home network",
                ],
                "when_not_needed": [
                    "Home WiFi/LAN — direct IP access works fine",
                    "Hermes (WSL) and CoAgent on same machine",
                    "Another device on the same LAN",
                ],
                "security": "Tunnels expose CoAgent to the internet. Always use --secure (token auth).",
            },
        })

    if action == "stop":
        ngrok_pid = _DEPLOY_STATE.get("ngrok_pid")
        if ngrok_pid:
            try:
                subprocess.run(["taskkill", "/PID", str(ngrok_pid), "/f"],
                               capture_output=True, timeout=10)
            except Exception:
                pass
        _DEPLOY_STATE["ngrok_url"] = None
        _DEPLOY_STATE["ngrok_pid"] = None
        return jsonify({"status": "stopped"})

    if action == "start":
        if not ngrok and _ensure_ngrok is not None:
            res = _ensure_ngrok(auth_token=payload.get("ngrok_authtoken"))
            if res.get("ok"):
                ngrok = res.get("path")
        if not ngrok:
            return _error(
                "ngrok not installed. Download from https://ngrok.com/download",
                status=500,
                help="Install ngrok, then retry. Needed for cellular/NAT access."
            )

        port = payload.get("port", _DEPLOY_STATE.get("port", 9123))
        try:
            ngrok_proc = subprocess.Popen(
                [ngrok, "http", str(port), "--log=stdout"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _DEPLOY_STATE["ngrok_pid"] = ngrok_proc.pid
            time.sleep(3)

            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=10) as resp:
                data = json.loads(resp.read())
            for t in data.get("tunnels", []):
                if t.get("proto") == "https":
                    _DEPLOY_STATE["ngrok_url"] = t["public_url"]
                    return jsonify({"status": "started", "url": t["public_url"]})
            return _error("Tunnel started but no HTTPS URL found", status=500)
        except Exception as e:
            return _error(f"Failed to start ngrok: {e}", status=500)

    return _error(f"Unknown action: {action}")


@deploy_bp.route("/deploy/script", methods=["GET"])
def route_deploy_script():
    """Download the standalone oneclick_deploy.ps1 script."""
    script = _generate_standalone_script()
    return Response(
        script,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=oneclick_deploy.ps1"},
    )


def _generate_standalone_script() -> str:
    """Generate a standalone PowerShell deploy script that works on fresh Windows."""
    return r'''# One-Click CoAgent Deploy — run this on any fresh Windows machine
# Usage: powershell -ExecutionPolicy Bypass -File oneclick_deploy.ps1

param(
    [int]$Port = 9123,
    [switch]$Tunnel,  # OPTIONAL: add ngrok tunnel (needed for cellular/NAT)
    [string]$NgrokAuthToken = ""
)

$ErrorActionPreference = "Stop"
Write-Host "=== CoAgent One-Click Deploy ===" -ForegroundColor Cyan
Write-Host ""

# Phase 1: Find Python
Write-Host "[1/4] Finding Python..." -ForegroundColor Yellow
$pythons = @(
    "python", "python3", "py",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "C:\Program Files\Python313\python.exe",
    "C:\Program Files\Python312\python.exe"
)
$python = $null
foreach ($p in $pythons) {
    $expanded = [Environment]::ExpandEnvironmentVariables($p)
    if (Test-Path $expanded) {
        $python = $expanded
        break
    }
    $found = Get-Command $p -ErrorAction SilentlyContinue
    if ($found) {
        $python = $found.Source
        break
    }
}
if (-not $python) {
    Write-Host "ERROR: Python 3.10+ not found!" -ForegroundColor Red
    Write-Host "Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    exit 1
}
Write-Host "  Python: $python" -ForegroundColor Green

# Phase 2: Clone/pull CoAgent
Write-Host "[2/4] Setting up CoAgent..." -ForegroundColor Yellow
$CoAgentDir = "$env:USERPROFILE\Desktop\Hermes CoAgent"
if (Test-Path $CoAgentDir) {
    Write-Host "  Already exists at: $CoAgentDir"
} else {
    Write-Host "  Downloading CoAgent..."
    git clone https://github.com/Predator04/Hermes-CoAgent.git "$CoAgentDir" 2>$null
    if (-not (Test-Path $CoAgentDir)) {
        # Fallback: download zip
        Invoke-WebRequest -Uri "https://github.com/Predator04/Hermes-CoAgent/archive/refs/heads/main.zip" -OutFile "$env:TEMP\coagent.zip"
        Expand-Archive "$env:TEMP\coagent.zip" -DestinationPath "$env:USERPROFILE\Desktop"
        Rename-Item "$env:USERPROFILE\Desktop\Hermes-CoAgent-main" "Hermes CoAgent"
    }
}

# Phase 3: Install deps
Write-Host "[3/4] Installing dependencies..." -ForegroundColor Yellow
& $python -m pip install --quiet --upgrade pip 2>$null
$packages = @("flask","waitress","pillow","pyautogui","pywinauto","pytesseract","pygetwindow","pyperclip","pystray","requests","mss","psutil","patchright")
foreach ($pkg in $packages) {
    Write-Host "  pip: $pkg"
    & $python -m pip install --quiet $pkg 2>$null
}
Write-Host "  Dependencies installed." -ForegroundColor Green

# Phase 4: Generate token + launch
Write-Host "[4/4] Launching CoAgent..." -ForegroundColor Yellow
$token = -join (1..64 | ForEach-Object { '{0:x}' -f ([System.Security.Cryptography.RandomNumberGenerator]::GetInt32(0, 16)) })
Set-Location $CoAgentDir

Write-Host ""
Write-Host "=== CoAgent is starting! ===" -ForegroundColor Green
Write-Host "  LAN URL:  http://127.0.0.1:$Port" -ForegroundColor White
Write-Host "  Token:    $token" -ForegroundColor White
Write-Host ""

# Save token
$token | Out-File -FilePath ".token" -Encoding ascii -NoNewline

# Start CoAgent
Start-Process -FilePath $python -ArgumentList "-B `"$CoAgentDir\hermes_coagent.py`" --secure --token=$token --allow-external --port=$Port" -WindowStyle Hidden

Start-Sleep 3

# Verify
try {
    $ping = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/ping" -TimeoutSec 10
    Write-Host "  Server ONLINE: $($ping.status)" -ForegroundColor Green
} catch {
    Write-Host "  Server starting... (may take a few more seconds)" -ForegroundColor Yellow
}

# Optional ngrok
if ($Tunnel) {
    Write-Host ""
    Write-Host "--- Ngrok Tunnel (Optional) ---" -ForegroundColor Cyan
    Write-Host "You need this if:" -ForegroundColor Yellow
    Write-Host "  * You're on T-Mobile/cellular (carriers block inbound)" -ForegroundColor Gray
    Write-Host "  * You're behind double NAT (apartment WiFi)" -ForegroundColor Gray
    Write-Host "  * You need outside access" -ForegroundColor Gray
    Write-Host ""
    Write-Host "You DON'T need this if:" -ForegroundColor Green
    Write-Host "  * You're on home WiFi/LAN" -ForegroundColor Gray
    Write-Host "  * Accessing from the same machine" -ForegroundColor Gray
    Write-Host ""

    $ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
    if (-not $ngrok) {
        Write-Host "  Ngrok not found. Install from: https://ngrok.com/download" -ForegroundColor Red
    } else {
        Write-Host "  Starting ngrok on port $Port..."
        Start-Process -FilePath "ngrok" -ArgumentList "http $Port --log=stdout" -WindowStyle Hidden
        Start-Sleep 3
        try {
            $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5
            $https = $tunnels.tunnels | Where-Object { $_.proto -eq "https" }
            if ($https) {
                Write-Host "  Ngrok URL: $($https.public_url)" -ForegroundColor Green
            }
        } catch {
            Write-Host "  Ngrok started (URL at http://127.0.0.1:4040)" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Done! CoAgent is running at http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "Token saved to: $CoAgentDir\.token" -ForegroundColor Cyan
'''


def register_routes(app, state, require_auth):
    """Register deploy routes on the Flask app."""
    for endpoint, view_func in list(deploy_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        deploy_bp.view_functions[endpoint] = wrapped

    app.register_blueprint(deploy_bp)
