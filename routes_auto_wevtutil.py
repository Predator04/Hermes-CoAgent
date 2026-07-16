# Auto-added feature: microsoft/windows (built-in) — wevtutil
# Description: wevtutil.exe — Windows Event Log management tool.
#   Query, export, archive, clear event logs from Application, System, Security,
#   Setup and custom logs. List log metadata, log publishers, and event subscriptions.
#   Essential for Windows diagnostics and automation.
# Source: Built-in Windows tool at C:\Windows\system32\wevtutil.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Event Log management — query, export, archive, and clear event logs from Application/System/Security channels; list log metadata, publishers, subscriptions, and log file paths",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil",
    "added": "2026-07-16",
    "command": "wevtutil <command> [args]",
}

def _find_wevtutil():
    """Locate wevtutil.exe — system32."""
    exe = shutil.which("wevtutil") or shutil.which("wevtutil.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\wevtutil.exe",
        r"C:\Windows\SysWOW64\wevtutil.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None

def _is_wevtutil_available():
    """Check wevtutil responds."""
    exe = _find_wevtutil()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False

def _run_wevtutil(args, timeout=30):
    """Run wevtutil.exe with given args, return output or raise."""
    exe = _find_wevtutil()
    if not exe:
        raise RuntimeError("wevtutil.exe not found on system")
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("wevtutil operation timed out")
    except OSError as e:
        raise RuntimeError(f"wevtutil execution failed: {e}")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "wevtutil returned non-zero exit code")
    return result.stdout

def _parse_log_lines(output):
    """Parse wevtutil output lines into a list of strings."""
    return [l.rstrip() for l in output.splitlines() if l.rstrip()]

def register_routes(app, state, require_auth):
    @app.route("/auto/wevtutil/info", methods=["GET"])
    @require_auth
    def route_auto_wevtutil_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/wevtutil/ping", methods=["GET"])
    @require_auth
    def route_auto_wevtutil_ping():
        try:
            available = _is_wevtutil_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "wevtutil (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/wevtutil/logs", methods=["GET"])
    @require_auth
    def route_auto_wevtutil_logs():
        """List all available event logs with metadata."""
        try:
            output = _run_wevtutil(["el"], timeout=15)
            logs = _parse_log_lines(output)
            return jsonify({
                "ok": True,
                "logs": logs,
                "count": len(logs),
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/wevtutil/log/info", methods=["POST"])
    @require_auth
    def route_auto_wevtutil_log_info():
        """Get metadata for a specific event log (path, max size, retention, etc.)."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        logname = (body.get("log") or "").strip()
        if not logname:
            return jsonify({"ok": False, "error": _missing_field("log")}), 400
        try:
            output = _run_wevtutil(["gl", logname], timeout=15)
            return jsonify({"ok": True, "log": logname, "metadata": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "log": logname, "error": str(e)}), 503

    @app.route("/auto/wevtutil/query", methods=["POST"])
    @require_auth
    def route_auto_wevtutil_query():
        """Query events from a log with optional filters."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        logname = (body.get("log") or "").strip()
        if not logname:
            return jsonify({"ok": False, "error": _missing_field("log")}), 400
        xpath = (body.get("xpath") or "").strip()
        max_events = int(body.get("max_events", 50))
        if max_events < 1:
            max_events = 50
        if max_events > 500:
            max_events = 500
        try:
            args = ["qe", logname, f"/count:{max_events}", "/f:text"]
            if xpath:
                args.append("/q:" + xpath)
            output = _run_wevtutil(args, timeout=30)
            events = _parse_log_lines(output)
            return jsonify({
                "ok": True,
                "log": logname,
                "events": events,
                "count": len(events),
                "max_events": max_events,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "log": logname, "error": str(e)}), 503

    @app.route("/auto/wevtutil/export", methods=["POST"])
    @require_auth
    def route_auto_wevtutil_export():
        """Export event log to an evtx file."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        logname = (body.get("log") or "").strip()
        export_path = (body.get("path") or "").strip()
        if not logname:
            return jsonify({"ok": False, "error": _missing_field("log")}), 400
        if not export_path:
            return jsonify({"ok": False, "error": _missing_field("path")}), 400
        if len(export_path) > 260:
            return jsonify({"ok": False, "error": "Export path too long (max 260 chars)"}), 400
        try:
            output = _run_wevtutil(["epl", logname, export_path], timeout=60)
            return jsonify({"ok": True, "log": logname, "export_path": export_path, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "log": logname, "error": str(e)}), 503

    @app.route("/auto/wevtutil/clear", methods=["POST"])
    @require_auth
    def route_auto_wevtutil_clear():
        """Clear all events from a log (and optionally save backup)."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        logname = (body.get("log") or "").strip()
        if not logname:
            return jsonify({"ok": False, "error": _missing_field("log")}), 400
        backup_path = (body.get("backup") or "").strip()
        try:
            args = ["cl", logname]
            if backup_path:
                args += [backup_path]
            output = _run_wevtutil(args, timeout=30)
            return jsonify({
                "ok": True,
                "log": logname,
                "backup": backup_path if backup_path else None,
                "output": output,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "log": logname, "error": str(e)}), 503

    @app.route("/auto/wevtutil/publishers", methods=["GET"])
    @require_auth
    def route_auto_wevtutil_publishers():
        """List all event log publishers/providers."""
        try:
            output = _run_wevtutil(["gp"], timeout=15)
            publishers = _parse_log_lines(output)
            return jsonify({
                "ok": True,
                "publishers": publishers,
                "count": len(publishers),
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/wevtutil/subscriptions", methods=["GET"])
    @require_auth
    def route_auto_wevtutil_subscriptions():
        """List configured event subscriptions."""
        try:
            output = _run_wevtutil(["gs"], timeout=15)
            subs = _parse_log_lines(output)
            return jsonify({
                "ok": True,
                "subscriptions": subs,
                "count": len(subs),
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/wevtutil/archive", methods=["POST"])
    @require_auth
    def route_auto_wevtutil_archive():
        """Archive a log: export to evtx then optionally clear the original."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        logname = (body.get("log") or "").strip()
        archive_path = (body.get("path") or "").strip()
        clear_after = body.get("clear", False)
        if not logname:
            return jsonify({"ok": False, "error": _missing_field("log")}), 400
        if not archive_path:
            return jsonify({"ok": False, "error": _missing_field("path")}), 400
        try:
            export_output = _run_wevtutil(["epl", logname, archive_path], timeout=60)
            result = {"ok": True, "log": logname, "archive_path": archive_path}
            if clear_after:
                clear_output = _run_wevtutil(["cl", logname], timeout=30)
                result["cleared"] = True
            return jsonify(result)
        except RuntimeError as e:
            return jsonify({"ok": False, "log": logname, "error": str(e)}), 503
