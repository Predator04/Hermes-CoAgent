# Auto-added feature: microsoft/windows (built-in) — taskkill
# Description: taskkill.exe — Terminate Windows processes by name, PID, or filter.
#   Supports remote process termination, subtree killing, force termination.
#   Essential companion to tasklist for process lifecycle automation.
# Source: Built-in Windows tool at C:\Windows\system32\taskkill.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Process Terminator — kill processes by PID, image name, or filter; force terminate, kill process trees, remote process termination, filter by window state/modules/services",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill",
    "added": "2026-07-16",
    "command": "taskkill [/s computer] [/u domain\\user [/p password]] [/fi filter] [/pid pid|/im imagename] [/f] [/t]",
}

def _find_taskkill():
    """Locate taskkill.exe — system32."""
    exe = shutil.which("taskkill") or shutil.which("taskkill.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\taskkill.exe",
        r"C:\Windows\SysWOW64\taskkill.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None

def _is_taskkill_available():
    """Check taskkill responds."""
    exe = _find_taskkill()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "/?"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False

def _run_taskkill(args, timeout=15):
    """Run taskkill.exe with given args, return result object or raise."""
    exe = _find_taskkill()
    if not exe:
        raise RuntimeError("taskkill.exe not found on system")
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("taskkill operation timed out")
    except OSError as e:
        raise RuntimeError(f"taskkill execution failed: {e}")
    return result

def _parse_taskkill_output(result):
    """Parse taskkill stdout/stderr into structured result."""
    parsed = {
        "exit_code": result.returncode,
        "success": result.returncode == 0,
        "message": "",
        "errors": [],
    }
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        parsed["message"] = stdout
    if stderr:
        for line in stderr.splitlines():
            stripped = line.strip()
            if stripped:
                parsed["errors"].append(stripped)
    return parsed

def _validate_target(body):
    """Validate that body has at least one of pid or name."""
    pid = body.get("pid")
    name = (body.get("name") or "").strip()
    if not pid and not name:
        return None, None, _missing_field("pid or name")
    return pid, name, None

def register_routes(app, state, require_auth):
    @app.route("/auto/taskkill/info", methods=["GET"])
    @require_auth
    def route_auto_taskkill_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/taskkill/ping", methods=["GET"])
    @require_auth
    def route_auto_taskkill_ping():
        try:
            available = _is_taskkill_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "taskkill (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/taskkill/pid", methods=["POST"])
    @require_auth
    def route_auto_taskkill_pid():
        """Kill a process by PID. Optionally force (-f) and kill subtree (-t)."""
        body = _json_body()
        pid = body.get("pid")
        force = bool(body.get("force", False))
        tree = bool(body.get("tree", False))
        if not pid:
            return _missing_field("pid")
        if not isinstance(pid, int) or isinstance(pid, bool):
            return jsonify({"ok": False, "error": f"Invalid pid: {pid} (must be an integer)"}), 400
        if pid <= 0:
            return jsonify({"ok": False, "error": "pid must be positive"}), 400
        args = ["/pid", str(pid)]
        if force:
            args.append("/f")
        if tree:
            args.append("/t")
        try:
            result = _run_taskkill(args)
            parsed = _parse_taskkill_output(result)
            return jsonify({
                "ok": parsed["success"],
                "pid": pid,
                "force": force,
                "tree": tree,
                "message": parsed["message"],
                "errors": parsed["errors"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "pid": pid, "error": str(e)}), 503

    @app.route("/auto/taskkill/name", methods=["POST"])
    @require_auth
    def route_auto_taskkill_name():
        """Kill process(es) by image name (e.g., 'notepad.exe'). Optionally force and subtree."""
        body = _json_body()
        name = (body.get("name") or "").strip()
        force = bool(body.get("force", False))
        tree = bool(body.get("tree", False))
        if not name:
            return _missing_field("name")
        if len(name) > 256:
            return jsonify({"ok": False, "error": "Image name too long (max 256 chars)"}), 400
        args = ["/im", name]
        if force:
            args.append("/f")
        if tree:
            args.append("/t")
        try:
            result = _run_taskkill(args)
            parsed = _parse_taskkill_output(result)
            return jsonify({
                "ok": parsed["success"],
                "name": name,
                "force": force,
                "tree": tree,
                "message": parsed["message"],
                "errors": parsed["errors"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "name": name, "error": str(e)}), 503

    @app.route("/auto/taskkill/filter", methods=["POST"])
    @require_auth
    def route_auto_taskkill_filter():
        """Kill processes matching one or more filters. Uses /fi parameters.
        Filter format: 'FILTERNAME eq VALUE' (e.g., 'USERNAME eq admin', 'STATUS eq running')
        Common filters: USERNAME, IMAGENAME, PID, SESSION, CPUTIME, MEMUSAGE, STATUS, WINDOWTITLE, SERVICES, MODULES"""
        body = _json_body()
        filters = body.get("filters")
        if not filters or not isinstance(filters, list):
            return _missing_field("filters (list)")
        force = bool(body.get("force", False))
        tree = bool(body.get("tree", False))
        if len(filters) > 10:
            return jsonify({"ok": False, "error": "Maximum 10 filters allowed"}), 400
        # Validate each filter: must be "FILTERNAME eq VALUE" or "FILTERNAME ne VALUE"
        _filter_re = re.compile(
            r'^(IMAGENAME|PID|SESSION|CPUTIME|MEMUSAGE|USERNAME|SERVICES|WINDOWTITLE|MODULES|STATUS)'
            r'\s+(eq|ne|gt|lt|ge|le)\s+\S.*$',
            re.IGNORECASE
        )
        args = []
        for f in filters:
            f_str = str(f).strip()
            if not f_str:
                continue
            if not _filter_re.match(f_str):
                return jsonify({"ok": False, "error": f"Invalid filter format: {f_str!r}. Expected: FILTERNAME eq VALUE"}), 400
            args.append("/fi")
            args.append(f_str)
        if not args:
            return jsonify({"ok": False, "error": "At least one valid filter required"}), 400
        # We must target by * (all matching) — taskkill /fi with wildcard
        args.append("/im")
        args.append("*")
        if force:
            args.append("/f")
        if tree:
            args.append("/t")
        try:
            result = _run_taskkill(args, timeout=15)
            parsed = _parse_taskkill_output(result)
            return jsonify({
                "ok": parsed["success"],
                "filters": filters,
                "force": force,
                "tree": tree,
                "message": parsed["message"],
                "errors": parsed["errors"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "filters": filters, "error": str(e)}), 503

    @app.route("/auto/taskkill/all", methods=["DELETE"])
    @require_auth
    def route_auto_taskkill_all():
        """Kill all processes by image name (wrapper for name endpoint with force+tree)."""
        body = _json_body()
        name = (body.get("name") or "").strip()
        if not name:
            return _missing_field("name")
        if len(name) > 256:
            return jsonify({"ok": False, "error": "Image name too long (max 256 chars)"}), 400
        args = ["/im", name, "/f", "/t"]
        try:
            result = _run_taskkill(args)
            parsed = _parse_taskkill_output(result)
            return jsonify({
                "ok": parsed["success"],
                "name": name,
                "force": True,
                "tree": True,
                "all": True,
                "message": parsed["message"],
                "errors": parsed["errors"],
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "name": name, "error": str(e)}), 503
