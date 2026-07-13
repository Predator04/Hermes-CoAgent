# Auto-added feature: microsoft/windows (built-in) — Tasklist + Taskkill
# Description: tasklist.exe / taskkill.exe — Windows process management CLI.
#   List running processes with detailed info (PID, session, memory),
#   filter by name, user, session, PID; kill processes by PID or name.
# Source: Built-in Windows tools at C:\Windows\system32\tasklist.exe / taskkill.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows process management — list all processes with PID/session/memory details, filter by name/user/PID/session, kill processes by PID or image name, force-terminate hung processes",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tasklist",
    "added": "2026-07-13",
    "command": "tasklist [/S system] [/M module] [/V] [/FI filter] [/FO format] & taskkill [/F] [/IM name | /PID pid]",
}

TASKLIST_HEADER_RE = re.compile(
    r"^Image Name\s+PID\s+Session Name\s+Session#\s+Mem Usage"
)

TASKLIST_LINE_RE = re.compile(
    r"^(.+?)\s+(\d+)\s+(\S+(?:\s+\S+)*?)\s+(\d+)\s+(\d[\d,]*\s*K)"
)

TASKLIST_VERBOSE_HEADER = re.compile(r"^Image Name:\s+(.+)$")

TASKLIST_MODULE_LINE = re.compile(
    r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d[\d,]*\s*K)"
)


def _find_tasklist():
    """Locate tasklist.exe — always in system32 on Windows."""
    exe = shutil.which("tasklist") or shutil.which("tasklist.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\tasklist.exe",
        r"C:\Windows\SysWOW64\tasklist.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _find_taskkill():
    """Locate taskkill.exe — always in system32 on Windows."""
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


def _is_tasklist_available():
    tl = _find_tasklist()
    tk = _find_taskkill()
    if not tl or not tk:
        return False
    try:
        result = subprocess.run([tl], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_tasklist(args, timeout=15):
    """Run tasklist with given args, return (stdout, stderr, exit_code)."""
    exe = _find_tasklist()
    if not exe:
        raise RuntimeError("tasklist not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _clean_filter(filter_str):
    """Validate a tasklist filter string for injection safety."""
    f = str(filter_str or "").strip()
    if not f:
        raise ValueError("filter must not be empty")
    if len(f) > 200:
        raise ValueError("filter too long (max 200 chars)")
    if "\x00" in f:
        raise ValueError("filter cannot contain null bytes")
    # Only allow safe characters for tasklist filters
    allowed_chars = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
        "_-'eqnltg*"
    )
    for c in f:
        if c not in allowed_chars:
            raise ValueError(
                f"filter contains disallowed character: {repr(c)}. "
                "Use basic alphanumeric filters like 'PID eq 1234' or 'IMAGENAME eq notepad.exe'"
            )
    return f


def _clean_image_name(name):
    """Validate an image/process name."""
    n = str(name or "").strip()
    if not n:
        raise ValueError("image name must not be empty")
    if len(n) > 260:
        raise ValueError("image name too long (max 260 chars)")
    if "\x00" in n:
        raise ValueError("image name cannot contain null bytes")
    forbidden = set('<>"|?*\x00')
    if any(c in n for c in forbidden):
        raise ValueError(f"image name contains forbidden characters: {forbidden & set(n)}")
    return n


def _clean_pid(pid_str):
    """Validate and return a PID integer."""
    try:
        pid = int(str(pid_str).strip())
    except (ValueError, TypeError):
        raise ValueError("PID must be a valid integer")
    if pid < 0 or pid > 4194304:
        raise ValueError("PID must be between 0 and 4194304")
    return pid


def register_routes(app, state, require_auth):

    @app.route("/auto/tasklist/info", methods=["GET"])
    @require_auth
    def route_auto_tasklist_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/tasklist/ping", methods=["GET"])
    @require_auth
    def route_auto_tasklist_ping():
        tl = _find_tasklist()
        tk = _find_taskkill()
        available = _is_tasklist_available()
        return jsonify({
            "status": "ok",
            "feature": "microsoft/windows",
            "available": available,
            "tools": {
                "tasklist": tl or "tasklist.exe",
                "taskkill": tk or "taskkill.exe",
            },
        })

    @app.route("/auto/tasklist/list", methods=["GET"])
    @require_auth
    def route_auto_tasklist_list():
        """List all running processes with standard output."""
        tl = _find_tasklist()
        if not tl:
            return jsonify({"ok": False, "error": "tasklist not found"}), 503

        try:
            stdout, stderr, rc = _run_tasklist(["/V"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "tasklist failed",
                }), 502

            lines = stdout.strip().split("\n")
            processes = []
            header_found = False
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped or "===" in line_stripped:
                    continue
                if TASKLIST_HEADER_RE.match(line_stripped):
                    header_found = True
                    continue
                if header_found:
                    m = TASKLIST_LINE_RE.match(line_stripped)
                    if m:
                        processes.append({
                            "image_name": m.group(1).strip(),
                            "pid": int(m.group(2)),
                            "session_name": m.group(3).strip(),
                            "session_num": int(m.group(4)),
                            "mem_usage": m.group(5).strip(),
                        })

            return jsonify({
                "ok": True,
                "count": len(processes),
                "processes": processes[:500],  # cap at 500 to avoid huge responses
                "total_found": len(processes),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "tasklist timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/tasklist/filter", methods=["POST"])
    @require_auth
    def route_auto_tasklist_filter():
        """List processes matching specific filters."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        filters_list = body.get("filters", [])
        if not isinstance(filters_list, list):
            return jsonify({"ok": False, "error": "filters must be a list"}), 400

        tl = _find_tasklist()
        if not tl:
            return jsonify({"ok": False, "error": "tasklist not found"}), 503

        args = []
        for f in filters_list:
            try:
                clean_f = _clean_filter(str(f))
            except ValueError as e:
                return jsonify({"ok": False, "error": f"invalid filter '{f}': {e}"}), 400
            args.append("/FI")
            args.append(clean_f)

        try:
            stdout, stderr, rc = _run_tasklist(args + ["/V"], timeout=15)
            if rc != 0:
                return jsonify({
                    "ok": False,
                    "error": stderr.strip() or "tasklist filter failed",
                }), 502

            lines = stdout.strip().split("\n")
            processes = []
            header_found = False
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped or "===" in line_stripped:
                    continue
                if TASKLIST_HEADER_RE.match(line_stripped):
                    header_found = True
                    continue
                if header_found:
                    m = TASKLIST_LINE_RE.match(line_stripped)
                    if m:
                        processes.append({
                            "image_name": m.group(1).strip(),
                            "pid": int(m.group(2)),
                            "session_name": m.group(3).strip(),
                            "session_num": int(m.group(4)),
                            "mem_usage": m.group(5).strip(),
                        })

            return jsonify({
                "ok": True,
                "filters": filters_list,
                "count": len(processes),
                "processes": processes,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "tasklist filter timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/tasklist/kill", methods=["POST"])
    @require_auth
    def route_auto_tasklist_kill():
        """Kill a process by PID or image name."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        pid_raw = body.get("pid", None)
        name_raw = body.get("name", None)
        force = body.get("force", False)

        if pid_raw is None and not name_raw:
            return jsonify({
                "ok": False,
                "error": _missing_field("pid or name (at least one required)"),
            }), 400

        tk = _find_taskkill()
        if not tk:
            return jsonify({"ok": False, "error": "taskkill not found"}), 503

        args = []
        if force:
            args.append("/F")

        target = None
        if pid_raw is not None:
            try:
                pid = _clean_pid(pid_raw)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            args.append("/PID")
            args.append(str(pid))
            target = f"PID {pid}"
        else:
            try:
                name = _clean_image_name(name_raw)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            args.append("/IM")
            args.append(name)
            target = name

        try:
            result = subprocess.run(
                [tk] + args, capture_output=True, text=True, timeout=15
            )
            return jsonify({
                "ok": result.returncode == 0,
                "target": target,
                "force": force,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "taskkill timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/tasklist/kill_by_name", methods=["POST"])
    @require_auth
    def route_auto_tasklist_kill_by_name():
        """Kill all processes with a given image name."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        name = body.get("name", "")
        force = body.get("force", True)

        try:
            name = _clean_image_name(name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        tk = _find_taskkill()
        if not tk:
            return jsonify({"ok": False, "error": "taskkill not found"}), 503

        args = ["/F"] if force else []
        args.extend(["/IM", name])

        try:
            result = subprocess.run(
                [tk] + args, capture_output=True, text=True, timeout=15
            )
            return jsonify({
                "ok": result.returncode == 0,
                "name": name,
                "force": force,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "taskkill by name timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
