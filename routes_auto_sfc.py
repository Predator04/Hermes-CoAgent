# Auto-added feature: microsoft/windows (built-in) — SFC
# Description: sfc.exe — System File Checker. Scans and verifies integrity of
#   all protected Windows system files. Replaces incorrect versions with correct
#   Microsoft versions. Pairs with DISM for complete Windows system health management.
# Source: Built-in Windows tool at C:\Windows\system32\sfc.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows System File Checker — scan and verify integrity of protected system files, repair corrupted files, log verification results, check last scan status",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/sfc",
    "added": "2026-07-09",
    "command": "sfc /scannow /verifyonly /verifyfile=<path>",
}


def _find_sfc():
    """Locate sfc.exe — prefer system32, fall back to PATH."""
    system32 = r"C:\Windows\system32\sfc.exe"
    if os.path.isfile(system32):
        return system32
    exe = shutil.which("sfc") or shutil.which("sfc.exe")
    if exe:
        return exe
    syswow64 = r"C:\Windows\SysWOW64\sfc.exe"
    if os.path.isfile(syswow64):
        return syswow64
    return None


def _is_sfc_available():
    """Check sfc responds by running a quick verify."""
    exe = _find_sfc()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "/?"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # sfc /? outputs to stderr; check both streams
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode in (0, 1) and len(output) > 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_sfc(args, timeout=120):
    """Run sfc.exe with given args, return parsed output or raise."""
    exe = _find_sfc()
    if not exe:
        raise RuntimeError("sfc.exe not found on system")
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("SFC operation timed out (this can take a while for /scannow)")
    except OSError as e:
        raise RuntimeError(f"SFC execution failed: {e}")
    # SFC can return 0 (no issues), 1 (corruption found but repaired), or other
    return result


def _parse_sfc_output(output):
    """Parse SFC output for key status indicators."""
    result = {
        "raw": output,
        "summary": "",
        "found_corruption": False,
        "repaired": False,
        "unable_to_repair": False,
        "details": [],
    }
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        result["details"].append(stripped)
        if "Windows Resource Protection" in stripped:
            result["summary"] = stripped
        if "found corrupt files" in stripped.lower():
            result["found_corruption"] = True
        lowered = stripped.lower()
        if "repaired" in lowered and "unable" not in lowered and "not repaired" not in lowered and "could not be repaired" not in lowered:
            result["repaired"] = True
        if "unable to repair" in lowered or "could not repair" in lowered:
            result["unable_to_repair"] = True
    return result


def register_routes(app, state, require_auth):
    @app.route("/auto/sfc/info", methods=["GET"])
    @require_auth
    def route_auto_sfc_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/sfc/ping", methods=["GET"])
    @require_auth
    def route_auto_sfc_ping():
        try:
            available = _is_sfc_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "SFC (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/sfc/scannow", methods=["POST"])
    @require_auth
    def route_auto_sfc_scannow():
        """Run sfc /scannow — full system file integrity check and repair."""
        try:
            result = _run_sfc(["/scannow"], timeout=300)
            parsed = _parse_sfc_output(result.stdout or result.stderr or "")
            return jsonify({
                "ok": True,
                "returncode": result.returncode,
                "summary": parsed["summary"],
                "found_corruption": parsed["found_corruption"],
                "repaired": parsed["repaired"],
                "unable_to_repair": parsed["unable_to_repair"],
                "output": parsed["raw"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sfc/verify", methods=["GET"])
    @require_auth
    def route_auto_sfc_verify():
        """Run sfc /verifyonly — quick integrity check without repair."""
        try:
            result = _run_sfc(["/verifyonly"], timeout=180)
            parsed = _parse_sfc_output(result.stdout or result.stderr or "")
            return jsonify({
                "ok": True,
                "returncode": result.returncode,
                "summary": parsed["summary"],
                "found_corruption": parsed["found_corruption"],
                "clean": not parsed["found_corruption"],
                "output": parsed["raw"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/sfc/verifyfile", methods=["POST"])
    @require_auth
    def route_auto_sfc_verifyfile():
        """Verify a specific file's integrity (must be a protected system file)."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        filepath = (body.get("file") or "").strip()
        if not filepath:
            return jsonify({"ok": False, "error": _missing_field("file")}), 400
        if len(filepath) > 260:
            return jsonify({"ok": False, "error": "File path too long (max 260 chars)"}), 400
        try:
            result = _run_sfc(["/VERIFYFILE=" + filepath], timeout=60)
            parsed = _parse_sfc_output(result.stdout or result.stderr or "")
            return jsonify({
                "ok": True,
                "file": filepath,
                "summary": parsed["summary"],
                "found_corruption": parsed["found_corruption"],
                "output": parsed["raw"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "file": filepath, "error": str(e)}), 503

    @app.route("/auto/sfc/status", methods=["GET"])
    @require_auth
    def route_auto_sfc_status():
        """Check last SFC scan log from CBS.log for previous results."""
        try:
            # SFC results are logged in CBS.log — check the last few lines
            cbs_log = r"C:\Windows\Logs\CBS\CBS.log"
            if not os.path.isfile(cbs_log):
                return jsonify({
                    "ok": True,
                    "info": "CBS log not found — no prior SFC scan data",
                })
            # Read last 50 lines for SFC entries
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 f"Get-Content '{cbs_log}' -Tail 100 -ErrorAction SilentlyContinue | Select-String 'SFC|sfc|System File Checker|Windows Resource Protection'"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": f"CBS log read failed: {result.stderr.strip() or 'unknown error'}",
                }), 503
            entries = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
            return jsonify({
                "ok": True,
                "log_entries": entries[-20:],  # Last 20 relevant entries
                "count": len(entries),
            })
        except (subprocess.TimeoutExpired, OSError) as e:
            return jsonify({"ok": False, "error": str(e)}), 503
