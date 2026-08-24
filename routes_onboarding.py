"""
Hermes CoAgent - First-run onboarding
=====================================
Guided setup page shown on fresh installs so users can:
  1. Pick access mode (local-only vs remote / other devices)
  2. See and copy their auth token (with regenerate option)
  3. Optionally start a public tunnel and get a phone-scannable URL (QR)
  4. Toggle auto-start on login (schtasks /Change /Enable|/Disable)

The blueprint is named "onboarding". A marker file .onboarded is written to
COAGENT_DIR on completion; while it is absent, GET / and GET /dashboard are
redirected to /setup by a before_request hook.

Auth model:
  * On first run (marker absent) all /onboard/* endpoints are reachable
    without a bearer token — the whole point is that the user has not yet
    seen the token they need to authenticate with.
  * After completion, the same endpoints require a valid bearer token so
    that a returning user cannot re-view the token by hitting /setup.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Blueprint, Response, jsonify, redirect, request

import auth as _auth
from shared import COAGENT_DIR, SERVER_PORT, _console, _log

# Optional QR encoder — falls back to text URL if not installed.
try:
    import qrcode as _qrcode  # noqa: F401
    _QR_AVAILABLE = True
except Exception:
    _QR_AVAILABLE = False


onboarding_bp = Blueprint("onboarding", __name__)

ONBOARDED_MARKER = COAGENT_DIR / ".onboarded"
ONBOARDING_CONFIG = COAGENT_DIR / "onboarding_config.json"
SCHEDULED_TASK_NAME = "CoAgent"  # matches install_coagent.py

TOKEN_PLACEHOLDER = "__HERMES_TOKEN_PLACEHOLDER__"

_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
)


# ── helpers ──────────────────────────────────────────────────────

def _is_onboarded() -> bool:
    try:
        return ONBOARDED_MARKER.exists()
    except OSError:
        return False


def _bind_host() -> str:
    """Detect whether the server is bound to 0.0.0.0 vs 127.0.0.1.

    We derive this from sys.argv (same source hermes_coagent.py uses when
    it picks bind_host) rather than a live socket introspection — the app
    context does not currently expose bind_host to route modules.
    """
    return "0.0.0.0" if "--allow-external" in sys.argv else "127.0.0.1"


def _lan_ip() -> str | None:
    """Best-effort LAN IP for QR URLs when no tunnel is up."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _load_choices() -> dict:
    try:
        if ONBOARDING_CONFIG.exists():
            return json.loads(ONBOARDING_CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        _console(f"[onboarding] config load failed: {exc}")
    return {}


def _save_choices(data: dict) -> None:
    """Persist onboarding choices atomically."""
    tmp = ONBOARDING_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, ONBOARDING_CONFIG)


def _first_run_or_authed() -> bool:
    """Access gate for /onboard/* endpoints.

    Open on first run (marker absent); requires bearer token afterward so a
    completed install cannot be re-scraped for its token by anyone with
    network reach to the port.

    Note: after onboarding we always require a valid bearer token — even when
    auth was booted disabled. Otherwise an unauthenticated caller could hit
    /onboard/token on a no-auth boot, mint a token via create_if_missing=True,
    and seize control of the install.
    """
    if not _is_onboarded():
        return True
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    import secrets as _secrets
    provided = header[7:]
    return bool(_auth.AUTH_TOKEN) and _secrets.compare_digest(provided, _auth.AUTH_TOKEN or "")


def _current_token(create_if_missing: bool = False) -> str | None:
    """Return the effective auth token, optionally creating one on demand."""
    token = _auth.AUTH_TOKEN or _auth._load_token()
    if token:
        return token
    if create_if_missing:
        token = _auth.generate_token()
        _auth.AUTH_TOKEN = token
        _auth.AUTH_ENABLED = True
        return token
    return None


def _tunnel_snapshot() -> dict:
    """Read live tunnel status from routes_media (best-effort)."""
    try:
        from routes_media import _tunnel_status_snapshot
        return _tunnel_status_snapshot()
    except Exception:
        return {"active": False, "url": None}


def _run_schtasks(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    exe = shutil.which("schtasks") or shutil.which("schtasks.exe") or r"C:\Windows\system32\schtasks.exe"
    try:
        p = subprocess.run(
            [exe, *args], capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def _autostart_enabled() -> bool | None:
    """Query the scheduled task's Enabled state. Returns None if not found."""
    if os.name != "nt":
        return None
    rc, out, _err = _run_schtasks(["/Query", "/TN", SCHEDULED_TASK_NAME, "/V", "/FO", "LIST"])
    if rc != 0:
        return None
    for raw in out.splitlines():
        line = raw.strip()
        # localised as "Scheduled Task State" or "Status" depending on Windows lang
        low = line.lower()
        if low.startswith("scheduled task state:") or low.startswith("status:"):
            value = line.split(":", 1)[1].strip().lower()
            if value in ("enabled", "ready", "running"):
                return True
            if value in ("disabled",):
                return False
    return None


def _autostart_task_exists() -> bool:
    """Return True if the CoAgent scheduled task exists (regardless of state)."""
    if os.name != "nt":
        return False
    rc, _out, _err = _run_schtasks(["/Query", "/TN", SCHEDULED_TASK_NAME])
    return rc == 0


def _create_autostart_task() -> tuple[bool, str]:
    """Create the on-logon scheduled task pointing at start_coagent.bat.

    Returns (ok, detail). Used when the user enables autostart but the task
    was never registered (e.g. installed via the ZIP method, which skips
    install_coagent.py's schtasks step)."""
    launcher = COAGENT_DIR / "start_coagent.bat"
    if not launcher.exists():
        return False, f"launcher not found: {launcher}"
    username = os.environ.get("USERNAME", "").strip()
    args = [
        "/Create", "/TN", SCHEDULED_TASK_NAME,
        "/TR", f'"{launcher}"',
        "/SC", "onlogon", "/IT", "/F", "/DELAY", "0000:30",
    ]
    if username:
        args += ["/RU", username]
    rc, _out, err = _run_schtasks(args)
    if rc != 0:
        return False, (err or "").strip() or "schtasks /Create failed"
    return True, ""


# ── routes ───────────────────────────────────────────────────────

@onboarding_bp.route("/setup", methods=["GET"])
def route_setup_page():
    """Render the inline onboarding HTML page.

    We deliberately do NOT gate this endpoint by require_auth: on a fresh
    install the user has never seen the token yet. Once completed, the
    before_request hook redirects /setup callers back to /dashboard so
    the token cannot be re-viewed.
    """
    if _is_onboarded():
        return redirect("/dashboard", code=302)

    # Ensure a token exists so the page can render it. If we mint one here,
    # persist it and flip AUTH_ENABLED so the tray / API can use it too.
    token = _current_token(create_if_missing=True) or ""
    html = ONBOARDING_HTML.replace(TOKEN_PLACEHOLDER, json.dumps(token)[1:-1])
    resp = Response(html, mimetype="text/html")
    resp.headers["Content-Security-Policy"] = _CSP
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@onboarding_bp.route("/onboard/status", methods=["GET"])
def route_onboard_status():
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    choices = _load_choices()
    tunnel = _tunnel_snapshot()
    return jsonify({
        "onboarded": _is_onboarded(),
        "token_set": bool(_auth.AUTH_TOKEN or _auth._load_token()),
        "bind_host": _bind_host(),
        "port": SERVER_PORT,
        "lan_ip": _lan_ip(),
        "tunnel_url": tunnel.get("url"),
        "tunnel_active": tunnel.get("active", False),
        "tunnel_tools": tunnel.get("tools", {}),
        "autostart": _autostart_enabled(),
        "qr_backend": "server" if _QR_AVAILABLE else "client",
        "access_mode": choices.get("access_mode"),
    })


@onboarding_bp.route("/onboard/token", methods=["GET"])
def route_onboard_token():
    """Reveal the current token in plaintext.

    Guarded by _first_run_or_authed so a completed install can only reveal
    the token to a caller that already knows it.
    """
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    token = _current_token(create_if_missing=True) or ""
    return jsonify({"token": token})


@onboarding_bp.route("/onboard/regenerate-token", methods=["POST"])
def route_onboard_regen():
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    new_token = _auth.generate_token()
    _auth.AUTH_TOKEN = new_token
    _auth.AUTH_ENABLED = True
    _log("[onboarding] token regenerated")
    return jsonify({"ok": True, "token": new_token})


@onboarding_bp.route("/onboard/tunnel", methods=["POST"])
def route_onboard_tunnel():
    """Delegate to the existing /tunnel/start route in routes_media.

    We proxy through HTTP with the bearer token so we reuse the full
    process-management + URL-detection logic without duplicating it.
    """
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    token = _auth.AUTH_TOKEN or _auth._load_token() or ""
    incoming = request.get_json(silent=True) or {}
    method = str(incoming.get("method") or "ngrok").strip().lower()
    if method not in {"ngrok", "cloudflare"}:
        method = "ngrok"
    ngrok_authtoken_raw = incoming.get("ngrok_authtoken")
    ngrok_authtoken = str(ngrok_authtoken_raw).strip() if isinstance(ngrok_authtoken_raw, str) else ""
    payload = {"method": method, "port": SERVER_PORT, "timeout": 25}
    if ngrok_authtoken:
        payload["ngrok_authtoken"] = ngrok_authtoken
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{SERVER_PORT}/tunnel/start",
        data=body_bytes,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            if not isinstance(data, dict):
                return jsonify({"ok": False, "error": "unexpected upstream body"}), 502
            # Preserve upstream fields but never let them clobber the outer
            # envelope ("ok" in particular).
            payload = {k: v for k, v in data.items() if k != "ok"}
            return jsonify({"ok": True, "url": data.get("url"), **payload})
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8", errors="replace") or "{}")
        except Exception:
            payload = {"error": str(e)}
        return jsonify({"ok": False, **payload}), e.code
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 502


@onboarding_bp.route("/onboard/autostart", methods=["POST"])
def route_onboard_autostart():
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if os.name != "nt":
        return jsonify({"ok": False, "error": "Autostart is Windows-only"}), 501
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    action = "/Enable" if enabled else "/Disable"
    if enabled and not _autostart_task_exists():
        ok, detail = _create_autostart_task()
        if not ok:
            return jsonify({
                "ok": False,
                "error": "failed to create autostart task",
                "detail": detail,
            }), 500
        _log("[onboarding] autostart task created (was missing); enabled")
        return jsonify({"ok": True, "enabled": True})
    rc, _out, err = _run_schtasks(["/Change", "/TN", SCHEDULED_TASK_NAME, action])
    if rc != 0:
        return jsonify({
            "ok": False,
            "error": f"schtasks {action} failed",
            "detail": err.strip() or "task not found (was CoAgent installed via install_coagent.py?)",
        }), 500
    _log(f"[onboarding] autostart {'enabled' if enabled else 'disabled'}")
    return jsonify({"ok": True, "enabled": enabled})


@onboarding_bp.route("/onboard/qr", methods=["GET"])
def route_onboard_qr():
    """Return a PNG QR code for the given ?text=... value.

    We generate server-side so the URL/token never leaves the machine. If
    the qrcode package is not installed we return 501 and the client falls
    back to displaying the URL as plain text.
    """
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if not _QR_AVAILABLE:
        return jsonify({"error": "qrcode module not installed"}), 501
    text = request.args.get("text", "").strip()
    if not text or len(text) > 2048:
        return jsonify({"error": "text is required (1..2048 chars)"}), 400
    try:
        import qrcode as qr
        img = qr.make(text, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        resp = Response(buf.getvalue(), mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as e:
        return jsonify({"error": f"QR generation failed: {type(e).__name__}: {e}"}), 500


@onboarding_bp.route("/onboard/complete", methods=["POST"])
def route_onboard_complete():
    if not _first_run_or_authed():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    access_mode = data.get("access_mode")
    if access_mode not in ("local", "remote"):
        access_mode = "local"
    choices = {
        "access_mode": access_mode,
        "tunnel_started": bool(data.get("tunnel_started")),
        "autostart": bool(data.get("autostart")) if data.get("autostart") is not None else None,
        "completed_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        _save_choices(choices)
        ONBOARDED_MARKER.write_text("1", encoding="utf-8")
    except OSError as e:
        return jsonify({"ok": False, "error": f"Failed to write marker: {e}"}), 500
    _log(f"[onboarding] completed (access_mode={access_mode})")
    return jsonify({"ok": True})


# ── inline HTML ──────────────────────────────────────────────────
# Dark theme matches routes_dashboard.py. Single page, JS-driven step
# navigation (no external libs). If server-side QR is unavailable, the
# tunnel/LAN URL is shown as text instead.

ONBOARDING_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'">
<title>Welcome to Hermes CoAgent</title>
<style>
:root{color-scheme:dark;--bg:#111318;--panel:#181c24;--panel2:#202632;--text:#f2f5f8;--muted:#9aa5b1;--accent:#2f7df6;--ok:#42d392;--bad:#ff6b6b;--line:#303846}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif}
header{padding:18px 20px;border-bottom:1px solid var(--line);background:#0f1217}
h1{font-size:20px;margin:0;font-weight:650}h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 12px}
main{max-width:820px;margin:0 auto;padding:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:16px}
.steps{display:flex;gap:8px;margin-bottom:20px}.step{flex:1;padding:10px;text-align:center;background:var(--panel2);border:1px solid var(--line);border-radius:8px;font-size:12px;color:var(--muted)}
.step.active{border-color:var(--accent);color:var(--text)}.step.done{border-color:var(--ok);color:var(--ok)}
.choice{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}
.choice label{display:block;padding:14px;background:var(--panel2);border:2px solid var(--line);border-radius:8px;cursor:pointer;transition:border-color .1s}
.choice label:hover{border-color:#4a5266}.choice input[type=radio]{margin-right:8px}
.choice input[type=radio]:checked + span{color:var(--accent)}.choice label.selected{border-color:var(--accent)}
.choice small{display:block;color:var(--muted);margin-top:4px;font-size:12px}
.token-row{display:flex;gap:8px;align-items:center;margin:12px 0}
.token-input{flex:1;background:#0d1016;color:var(--text);border:1px solid var(--line);border-radius:5px;padding:9px 10px;font-family:ui-monospace,Consolas,Menlo,monospace;font-size:12px}
button{background:var(--accent);color:#fff;border:0;border-radius:5px;padding:9px 14px;cursor:pointer;font-size:13px}
button.secondary{background:#2a3140;color:var(--text)}button.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}
button:disabled{opacity:.45;cursor:not-allowed}
.qr-box{display:flex;gap:16px;align-items:center;padding:12px;background:var(--panel2);border-radius:8px;margin-top:10px}
.qr-box img{background:#fff;padding:6px;border-radius:6px;width:180px;height:180px}
.url{flex:1;word-break:break-all;font-family:ui-monospace,Consolas,Menlo,monospace;font-size:12px;color:var(--muted)}
.toggle{display:flex;align-items:center;gap:10px;padding:10px 0}
.notice{padding:10px;background:#1a1f2b;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:5px;color:var(--muted);font-size:12px;margin:10px 0}
.notice.warn{border-left-color:#f0a020;color:#f0a020}.notice.err{border-left-color:var(--bad);color:var(--bad)}
.nav{display:flex;justify-content:space-between;margin-top:20px}
.hidden{display:none}
</style>
</head>
<body>
<header><h1>Welcome to Hermes CoAgent</h1></header>
<main>
  <div class="steps">
    <div class="step active" id="s1">1. Access</div>
    <div class="step" id="s2">2. Token</div>
    <div class="step" id="s3">3. Connect</div>
  </div>

  <!-- Step 1: Access mode -->
  <div class="card" id="step1">
    <h2>How will you connect?</h2>
    <div class="choice">
      <label><input type="radio" name="mode" value="local" checked><span>This computer only</span>
        <small>Safest. Only apps on this PC can talk to CoAgent.</small></label>
      <label><input type="radio" name="mode" value="remote"><span>My other devices too</span>
        <small>Enables tunnel + QR so a phone or another PC can reach it.</small></label>
    </div>
    <div id="mode-warn" class="notice warn hidden">
      Remote access requires the server to be bound to all interfaces (<code>--allow-external</code>) or a tunnel.
      Current bind host: <code id="bindHost">?</code>.
    </div>
    <div class="nav"><span></span><button onclick="goto(2)">Continue</button></div>
  </div>

  <!-- Step 2: Token -->
  <div class="card hidden" id="step2">
    <h2>Your auth token</h2>
    <p style="margin:0 0 6px;color:var(--muted)">Copy this — every request to CoAgent needs it as a Bearer token.</p>
    <div class="token-row">
      <input class="token-input" id="tokenField" readonly value="">
      <button class="secondary" onclick="copyToken()" id="copyBtn">Copy</button>
      <button class="ghost" onclick="regenToken()" id="regenBtn">Regenerate</button>
    </div>
    <div id="tokenMsg" class="notice hidden"></div>
    <div class="nav"><button class="secondary" onclick="goto(1)">Back</button><button onclick="goto(3)">Continue</button></div>
  </div>

  <!-- Step 3: Connect -->
  <div class="card hidden" id="step3">
    <h2>Connect other devices</h2>
    <div id="remoteBlock">
      <p style="margin:0 0 8px;color:var(--muted)">Start a tunnel to get a public URL your phone can scan.</p>
      <div style="margin:8px 0">
        <label style="margin-right:14px"><input type="radio" name="tunnelMethod" value="ngrok" checked onchange="onMethodChange()"> ngrok (recommended)</label>
        <label><input type="radio" name="tunnelMethod" value="cloudflare" onchange="onMethodChange()"> Cloudflare</label>
      </div>
      <div id="ngrokBlock">
        <label for="ngrokToken" style="display:block;color:var(--muted);font-size:12px;margin:6px 0 4px">
          Ngrok authtoken (optional). <a href="https://dashboard.ngrok.com/get-started/your-authtoken" target="_blank" rel="noopener">Get your authtoken</a>.
        </label>
        <input class="token-input" id="ngrokToken" type="text" placeholder="paste your ngrok authtoken here" autocomplete="off" style="width:100%">
        <p style="color:var(--muted);font-size:12px;margin:6px 0 0">
          1. Create a free account at ngrok.com. 2. Copy your authtoken from the dashboard. 3. Paste it here. 4. Click Start tunnel.
        </p>
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button id="tunnelBtn" onclick="startTunnel()">Start tunnel</button>
        <span id="tunnelStatus" style="color:var(--muted);font-size:12px"></span>
      </div>
      <div id="qrBox" class="qr-box hidden">
        <img id="qrImg" alt="QR code" />
        <div class="url" id="qrUrl"></div>
      </div>
    </div>
    <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
    <div class="toggle">
      <label><input type="checkbox" id="autostartChk"> Start CoAgent automatically when I log in</label>
      <span id="autostartMsg" style="color:var(--muted);font-size:12px"></span>
    </div>
    <div class="nav"><button class="secondary" onclick="goto(2)">Back</button><button onclick="complete()" id="completeBtn">Finish setup</button></div>
  </div>

  <div id="pageMsg"></div>
</main>

<script>
// Token is injected by the server so we don't need a round-trip on first paint.
const TOKEN_INJECTED = "__HERMES_TOKEN_PLACEHOLDER__";
let token = TOKEN_INJECTED || "";
let state = { mode: "local", tunnel_url: null, autostart: null, qr_backend: "server" };
let currentStep = 1;

function h(json) {
  const hdr = { "Content-Type": "application/json" };
  if (token) hdr["Authorization"] = "Bearer " + token;
  return hdr;
}

async function loadStatus() {
  try {
    const r = await fetch("/onboard/status", { headers: h() });
    if (!r.ok) return;
    const d = await r.json();
    state.qr_backend = d.qr_backend || "server";
    document.getElementById("bindHost").textContent = d.bind_host + ":" + d.port;
    if (d.bind_host !== "0.0.0.0") {
      document.getElementById("mode-warn").classList.remove("hidden");
    }
    if (typeof d.autostart === "boolean") {
      document.getElementById("autostartChk").checked = d.autostart;
      state.autostart = d.autostart;
    }
    if (d.tunnel_url) {
      state.tunnel_url = d.tunnel_url;
      showQr(d.tunnel_url);
    }
    // If token wasn't injected (paranoid fallback), fetch it now.
    if (!token) {
      const tr = await fetch("/onboard/token", { headers: h() });
      if (tr.ok) { token = (await tr.json()).token || ""; }
    }
    document.getElementById("tokenField").value = token;
  } catch (e) { /* non-fatal on first paint */ }
}

function goto(n) {
  currentStep = n;
  for (let i = 1; i <= 3; i++) {
    document.getElementById("step" + i).classList.toggle("hidden", i !== n);
    const s = document.getElementById("s" + i);
    s.classList.toggle("active", i === n);
    s.classList.toggle("done", i < n);
  }
  // Sync selected radio → state
  const sel = document.querySelector('input[name=mode]:checked');
  if (sel) state.mode = sel.value;
  // Hide remote block if local-only was chosen
  if (n === 3) {
    document.getElementById("remoteBlock").classList.toggle("hidden", state.mode === "local");
  }
}

async function copyToken() {
  const f = document.getElementById("tokenField");
  try {
    await navigator.clipboard.writeText(f.value);
    setMsg("tokenMsg", "Copied to clipboard", "ok");
  } catch (e) {
    f.select(); document.execCommand && document.execCommand("copy");
    setMsg("tokenMsg", "Copied (fallback)", "ok");
  }
}

async function regenToken() {
  if (!confirm("Regenerate the token? Any client using the old one will need to be updated.")) return;
  const btn = document.getElementById("regenBtn"); btn.disabled = true;
  try {
    const r = await fetch("/onboard/regenerate-token", { method: "POST", headers: h() });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "failed");
    token = d.token;
    document.getElementById("tokenField").value = token;
    setMsg("tokenMsg", "New token generated", "ok");
  } catch (e) {
    setMsg("tokenMsg", "Failed: " + e.message, "err");
  } finally { btn.disabled = false; }
}

function onMethodChange() {
  const methodEl = document.querySelector('input[name=tunnelMethod]:checked');
  const method = methodEl ? methodEl.value : "ngrok";
  const ngrokBlock = document.getElementById("ngrokBlock");
  if (ngrokBlock) ngrokBlock.style.display = (method === "ngrok") ? "" : "none";
}

async function startTunnel() {
  const btn = document.getElementById("tunnelBtn");
  const methodEl = document.querySelector('input[name=tunnelMethod]:checked');
  const method = methodEl ? methodEl.value : "ngrok";
  const tokenEl = document.getElementById("ngrokToken");
  const authtoken = tokenEl ? (tokenEl.value || "").trim() : "";
  const origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Starting...";
  document.getElementById("tunnelStatus").textContent = "Starting the tunnel. This may take a few seconds.";
  try {
    const r = await fetch("/onboard/tunnel", {
      method: "POST", headers: h(),
      body: JSON.stringify({ method: method, ngrok_authtoken: authtoken }),
    });
    const d = await r.json();
    if (!r.ok || !d.url) {
      const msg = d.help || d.error || d.detail || "Tunnel start failed.";
      throw new Error(msg);
    }
    state.tunnel_url = d.url;
    document.getElementById("tunnelStatus").textContent = "Public URL ready.";
    showQr(d.url);
  } catch (e) {
    document.getElementById("tunnelStatus").textContent = "";
    setPageMsg("Tunnel failed. " + e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = origLabel || "Start tunnel";
  }
}

async function showQr(url) {
  // Mint a short-lived, single-use handoff code instead of embedding the
  // permanent token in the QR. The code maps to the real token server-side
  // and is exchanged by the dashboard on scan, so the permanent token never
  // leaves the machine in a URL or a scannable image.
  let full = url;
  try {
    const r = await fetch("/auth/phone-link", { method: "POST", headers: h(), body: "{}" });
    const d = await r.json();
    if (r.ok && d.code) {
      full = url + (url.includes("?") ? "&" : "?") + "handoff=" + encodeURIComponent(d.code);
    }
  } catch (e) { /* fall back to plain URL — user can enter token manually */ }
  document.getElementById("qrUrl").textContent = full;
  const box = document.getElementById("qrBox");
  box.classList.remove("hidden");
  const img = document.getElementById("qrImg");
  if (state.qr_backend === "server") {
    img.src = "/onboard/qr?text=" + encodeURIComponent(full);
    img.onerror = () => { img.classList.add("hidden"); };
  } else {
    img.classList.add("hidden");
  }
}

document.getElementById("autostartChk").addEventListener("change", async (e) => {
  const wanted = e.target.checked;
  const msg = document.getElementById("autostartMsg");
  msg.textContent = wanted ? "Enabling…" : "Disabling…";
  try {
    const r = await fetch("/onboard/autostart", {
      method: "POST", headers: h(),
      body: JSON.stringify({ enabled: wanted }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || d.error || "failed");
    state.autostart = wanted;
    msg.textContent = wanted ? "Will start at login" : "Auto-start disabled";
  } catch (err) {
    e.target.checked = !wanted;
    msg.textContent = "Failed: " + err.message;
  }
});

async function complete() {
  const btn = document.getElementById("completeBtn"); btn.disabled = true;
  try {
    const r = await fetch("/onboard/complete", {
      method: "POST", headers: h(),
      body: JSON.stringify({
        access_mode: state.mode,
        tunnel_started: !!state.tunnel_url,
        autostart: state.autostart,
      }),
    });
    if (!r.ok) throw new Error((await r.json()).error || "failed");
    // Hand the session off via a single-use handoff code — never put the
    // permanent token in the URL (it would land in browser history and
    // server/tunnel access logs).
    let next = "/";
    try {
      const hc = await fetch("/auth/phone-link", { method: "POST", headers: h(), body: "{}" });
      const hd = await hc.json();
      if (hc.ok && hd.code) next = "/?handoff=" + encodeURIComponent(hd.code);
    } catch (e) { /* fall back to bare root; user can paste token manually */ }
    location.href = next;
  } catch (e) {
    setPageMsg("Setup could not be saved: " + e.message, "err");
    btn.disabled = false;
  }
}

function setMsg(id, text, kind) {
  const el = document.getElementById(id);
  el.className = "notice " + (kind === "err" ? "err" : kind === "warn" ? "warn" : "");
  el.textContent = text;
  el.classList.remove("hidden");
}
function setPageMsg(text, kind) {
  const el = document.getElementById("pageMsg");
  el.innerHTML = '<div class="notice ' + (kind || "") + '">' + text.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])) + '</div>';
}

document.querySelectorAll('input[name=mode]').forEach(el => {
  el.addEventListener("change", () => { state.mode = el.value; });
});

loadStatus();
</script>
</body>
</html>"""


# ── registration ─────────────────────────────────────────────────

def _install_first_run_redirect(app):
    """Redirect / and /dashboard to /setup while the marker is absent.

    Registered as a before_request hook (rather than editing route_index) so
    routes_dashboard.py needs no changes. Only intercepts GET /, /dashboard.
    """
    def _first_run_gate():
        if request.method != "GET":
            return None
        path = request.path
        if path not in ("/", "/dashboard"):
            return None
        if _is_onboarded():
            return None
        return redirect("/setup", code=302)

    app.before_request(_first_run_gate)


def register_routes(app, state, require_auth):  # noqa: ARG001 — signature matches sibling modules
    app.register_blueprint(onboarding_bp)
    _install_first_run_redirect(app)
    _log(f"[onboarding] routes registered (qr_backend={'server' if _QR_AVAILABLE else 'client'})")
