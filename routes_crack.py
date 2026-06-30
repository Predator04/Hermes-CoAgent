"""
Electret USB Dongle Crack — CoAgent integration route.
Launches Electret_.exe with the V5 DIAG DLL dongle emulator via stub injector,
captures a screenshot, and returns the result as a CoAgent endpoint.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, send_file

from shared import COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes

crack_bp = Blueprint("crack", __name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
CRACK_DIR = Path("C:/tmp")
STUB_EXE = CRACK_DIR / "electret_stub_v7.exe"
HOOK_DLL = CRACK_DIR / "wh_hook_dll_v2.dll"
TARGET_EXE = CRACK_DIR / "electret_work" / "Electret_.exe"
TARGET_DB = CRACK_DIR / "electret_work" / "DataBase" / "DataBase.mdb"

# Backup paths — where we keep safe copies
BACKUP_DIR = CRACK_DIR / "backups"
BACKUP_STUB = BACKUP_DIR / "electret_stub_v7.exe"
BACKUP_DLL = BACKUP_DIR / "wh_hook_dll_v2.dll"

# Log files
STUB_LOG = CRACK_DIR / "stub_v7_log.txt"
SHIM_LOG = CRACK_DIR / "shim_electret_v2_log.txt"
SCREENSHOT = CRACK_DIR / "crack_screenshot.png"

# ── State ─────────────────────────────────────────────────────────────────────
_CRACK_STATE: dict = {
    "last_run": None,
    "last_status": None,
    "last_exit_code": None,
    "runs_attempted": 0,
    "dongle_intercepts": 0,
    "running": False,
}


def _ensure_artifacts() -> list[str]:
    """Check all required crack artifacts exist. Returns list of missing items."""
    errors = []
    if not STUB_EXE.is_file():
        errors.append(f"stub missing: {STUB_EXE}")
    if not HOOK_DLL.is_file():
        errors.append(f"hook DLL missing: {HOOK_DLL}")
    if not TARGET_EXE.is_file():
        errors.append(f"target EXE missing: {TARGET_EXE}")
    if not TARGET_DB.is_file():
        errors.append(f"target DB missing: {TARGET_DB}")
    return errors


def _take_screenshot(output_path: Path) -> tuple[bool, str]:
    """
    Capture the desktop via PowerShell + scheduled task (runs in user session).
    Returns (success, message).
    """
    ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {{
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $bitmap.Save('{output_path.as_posix()}', [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output 'OK'
}} catch {{
    Write-Output "FAIL: $($_.Exception.Message)"
}}
$graphics.Dispose()
$bitmap.Dispose()
"""
    # Write the capture script
    ps_file = CRACK_DIR / "_crack_capture.ps1"
    ps_file.write_text(ps_script, encoding="utf-8")
    bat_file = CRACK_DIR / "_crack_capture.bat"
    bat_file.write_text(
        f'@echo off\npowershell -ExecutionPolicy Bypass -File "{ps_file.as_posix()}"\n',
        encoding="utf-8",
    )

    try:
        # Schedule it in the user session (session 1, not session 0)
        task_name = f"CrackCapture_{os.getpid()}"
        subprocess.run(
            [
                "schtasks.exe",
                "/create",
                "/tn", task_name,
                "/tr", str(bat_file),
                "/sc", "once",
                "/st", "00:00",
                "/ru", "Admin",
                "/rl", "highest",
                "/f",
            ],
            capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["schtasks.exe", "/run", "/tn", task_name],
            capture_output=True, text=True, timeout=10,
        )
        # Wait for capture to complete
        time.sleep(5)
        # Clean up the task
        subprocess.run(
            ["schtasks.exe", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        return False, f"scheduled task failed: {exc}"
    finally:
        # Clean up temp scripts
        try:
            ps_file.unlink(missing_ok=True)
            bat_file.unlink(missing_ok=True)
        except Exception:
            pass

    if output_path.is_file() and output_path.stat().st_size > 1000:
        return True, f"screenshot saved ({output_path.stat().st_size} bytes)"
    return False, "screenshot file missing or too small"


# ── Routes ────────────────────────────────────────────────────────────────────


@crack_bp.route("/crack/status", methods=["GET"])
def crack_status():
    """Return current crack state and artifact validation."""
    missing = _ensure_artifacts()
    return jsonify({
        "ready": len(missing) == 0,
        "missing": missing,
        "state": _CRACK_STATE,
        "paths": {
            "stub": str(STUB_EXE),
            "dll": str(HOOK_DLL),
            "target": str(TARGET_EXE),
            "stub_log_exists": STUB_LOG.is_file(),
            "shim_log_exists": SHIM_LOG.is_file(),
        },
    })


@crack_bp.route("/crack/run", methods=["POST"])
def crack_run():
    """
    Run the Electret crack: inject DLL, launch program, wait, screenshot.
    Body (JSON, optional):
      {
        "timeout": 20          # how long to wait before screenshot (seconds)
        "screenshot": true     # capture screenshot after timeout
      }
    """
    body = _json_body() or {}
    timeout = max(5, min(120, int(body.get("timeout", 20))))
    take_screenshot = bool(body.get("screenshot", True))

    # Check readiness
    missing = _ensure_artifacts()
    if missing:
        return jsonify({"error": "missing artifacts", "missing": missing}), 400

    if _CRACK_STATE["running"]:
        return jsonify({"error": "crack already running"}), 409

    # Clear old logs
    for log in (STUB_LOG, SHIM_LOG, SCREENSHOT):
        try:
            log.unlink(missing_ok=True)
        except Exception:
            pass

    _CRACK_STATE["running"] = True
    _CRACK_STATE["runs_attempted"] += 1
    _CRACK_STATE["last_run"] = datetime.now().isoformat()

    try:
        _console("[CRACK] Launching Electret via stub injector...")

        # Launch the stub injector (background)
        stub_proc = subprocess.Popen(
            [str(STUB_EXE), str(TARGET_EXE)],
            cwd=str(CRACK_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )

        # Wait for the program to run (stub waits for child to exit)
        start = time.monotonic()
        try:
            stdout_data, stderr_data = stub_proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stub_proc.kill()
            stdout_data, stderr_data = stub_proc.communicate(timeout=5)
            timed_out = True
        else:
            timed_out = False

        elapsed = round(time.monotonic() - start, 2)

        # Read logs
        stub_log_text = ""
        if STUB_LOG.is_file():
            stub_log_text = STUB_LOG.read_text(encoding="utf-8", errors="replace")
        shim_log_text = ""
        if SHIM_LOG.is_file():
            shim_log_text = SHIM_LOG.read_text(encoding="utf-8", errors="replace")

        # Count dongle intercepts
        dongle_count = shim_log_text.count("DONGLE MATCH")
        _CRACK_STATE["dongle_intercepts"] = dongle_count
        _CRACK_STATE["last_exit_code"] = stub_proc.returncode

        # Parse exit code from stub log
        exit_code = stub_proc.returncode
        for line in stub_log_text.splitlines():
            if "Electret_ exit:" in line:
                parts = line.split()
                for part in parts:
                    if part.startswith("0x") or part.isdigit():
                        try:
                            exit_code = int(part, 16) if part.startswith("0x") else int(part)
                        except ValueError:
                            pass
                        break

        result = {
            "success": dongle_count > 0 or exit_code == 0,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed,
            "timed_out": timed_out,
            "dongle_intercepts": dongle_count,
            "stub_log": stub_log_text[:2000],
            "shim_log_tail": shim_log_text[-1000:],
            "pid": stub_proc.pid,
            "stub_stdout": (stdout_data or b"").decode("utf-8", errors="replace")[:500],
            "stub_stderr": (stderr_data or b"").decode("utf-8", errors="replace")[:500],
        }

        _CRACK_STATE["last_status"] = "dongle_hit" if dongle_count > 0 else "no_dongle"
        _console(f"[CRACK] Run complete — exit={exit_code}, dongle={dongle_count}, elapsed={elapsed}s")

        # Take screenshot
        if take_screenshot:
            _console("[CRACK] Capturing screenshot...")
            ss_ok, ss_msg = _take_screenshot(SCREENSHOT)
            result["screenshot"] = {
                "captured": ss_ok,
                "message": ss_msg,
                "path": str(SCREENSHOT) if ss_ok else None,
            }
            if ss_ok:
                result["screenshot_url"] = f"/crack/screenshot/{os.path.basename(SCREENSHOT)}"

        return jsonify(result)

    except Exception as exc:
        _console(f"[CRACK] Error: {exc}")
        return jsonify({"error": str(exc)}), 500
    finally:
        _CRACK_STATE["running"] = False


@crack_bp.route("/crack/screenshot/<filename>", methods=["GET"])
def crack_screenshot(filename):
    """Serve the last captured crack screenshot."""
    safe = Path(filename).name  # prevent path traversal
    screenshot_path = CRACK_DIR / safe
    if not screenshot_path.is_file():
        screenshot_path = SCREENSHOT
    if not screenshot_path.is_file():
        return jsonify({"error": "no screenshot available"}), 404
    return send_file(
        str(screenshot_path),
        mimetype="image/png",
        as_attachment=False,
    )


@crack_bp.route("/crack/logs", methods=["GET"])
def crack_logs():
    """Return latest stub and shim logs."""
    result = {}
    if STUB_LOG.is_file():
        result["stub_log"] = STUB_LOG.read_text(encoding="utf-8", errors="replace")
    if SHIM_LOG.is_file():
        result["shim_log"] = SHIM_LOG.read_text(encoding="utf-8", errors="replace")
    return jsonify(result)


@crack_bp.route("/crack/restore", methods=["POST"])
def crack_restore():
    """Restore crack files from backup if originals are corrupted."""
    results = {}
    for name, src, dst in [
        ("stub", BACKUP_STUB, STUB_EXE),
        ("dll", BACKUP_DLL, HOOK_DLL),
    ]:
        if src.is_file():
            shutil.copy2(str(src), str(dst))
            results[name] = f"restored from {src.name}"
        else:
            results[name] = f"backup not found: {src}"
    return jsonify({"restored": results})


# ── Registration ──────────────────────────────────────────────────────────────


def register_routes(app, state, require_auth):
    """Register the crack routes with the CoAgent Flask app."""
    app.register_blueprint(crack_bp)
    _wrap_registered_blueprint_routes(app, crack_bp.name, require_auth)

    # Log status on load
    missing = _ensure_artifacts()
    if missing:
        _console(f"[CRACK] Loaded — missing artifacts: {len(missing)}")
        for m in missing:
            _console(f"  MISSING: {m}")
    else:
        _console("[CRACK] Loaded — all artifacts present")
        _console(f"  Stub:  {STUB_EXE}")
        _console(f"  DLL:   {HOOK_DLL}")
        _console(f"  Target:{TARGET_EXE}")
        _console(f"  DB:    {TARGET_DB}")
        if SCREENSHOT.is_file():
            _console(f"  Screenshot: {SCREENSHOT} ({SCREENSHOT.stat().st_size} bytes)")

    state["crack"] = {
        "available": len(missing) == 0,
        "missing": missing,
        "stub_log": str(STUB_LOG),
        "shim_log": str(SHIM_LOG),
        "screenshot": str(SCREENSHOT),
    }
