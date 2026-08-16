# Auto-added feature: microsoft/windows (built-in) — SchTasks
# Description: schtasks.exe — Windows Task Scheduler CLI: create, query, run,
#   change, end, and delete scheduled tasks on local or remote systems
# Source: Built-in Windows tool at C:\Windows\system32\schtasks.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Task Scheduler CLI — query/create/run/change/end/delete scheduled tasks, query task folders, view task details, manage task scheduler state",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks",
    "added": "2026-07-17",
    "command": "schtasks <Query|Create|Run|End|Change|Delete> [/S system] [/U user] [/P password]",
}

ENDPOINTS = {
    "query": "List all scheduled tasks (optionally filtered by folder or task name)",
    "query_detail": "Get detailed XML or verbose info about a specific task",
    "run": "Run a scheduled task immediately",
    "end": "Stop a running scheduled task",
    "delete": "Delete a scheduled task",
    "create_basic": "Create a basic scheduled task (run program on schedule)",
    "change": "Change properties of an existing task",
    "folders": "List task scheduler folders",
}


def _find_schtasks():
    exe = shutil.which("schtasks") or shutil.which("schtasks.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\schtasks.exe",
        r"C:\Windows\SysWOW64\schtasks.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_schtasks_available():
    exe = _find_schtasks()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_schtasks(args, timeout=20):
    exe = _find_schtasks()
    if not exe:
        raise RuntimeError("schtasks not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def register_routes(app, state, require_auth):
    _log("register_routes: schtasks")

    @app.route("/auto/schtasks/info", methods=["GET"])
    @require_auth
    def route_auto_schtasks_info():
        return jsonify({
            "ok": True,
            "feature": "schtasks",
            "info": FEATURE_INFO,
            "endpoints": ENDPOINTS,
            "available": _is_schtasks_available(),
        })

    @app.route("/auto/schtasks/ping", methods=["GET"])
    @require_auth
    def route_auto_schtasks_ping():
        available = _is_schtasks_available()
        return jsonify({
            "ok": available,
            "feature": "schtasks",
            "available": available,
        })

    @app.route("/auto/schtasks/query", methods=["GET"])
    @require_auth
    def route_auto_schtasks_query():
        """List all scheduled tasks or filter by folder/task name."""
        try:
            from flask import request
            task_path = request.args.get("path", "\\")
            folder = request.args.get("folder", "")
            format_type = request.args.get("format", "TABLE").upper()
        except Exception:
            task_path = "\\"
            folder = ""
            format_type = "TABLE"

        if format_type not in ("TABLE", "CSV", "XML"):
            format_type = "TABLE"

        args = ["Query", "/FO", format_type]
        # /NH (no header) is only valid with TABLE/CSV output.
        if format_type in ("TABLE", "CSV"):
            args.append("/NH")
        if folder:
            args.extend(["/TN", folder])
        elif task_path:
            args.extend(["/TN", task_path])

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "format": format_type,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/query/detail", methods=["GET"])
    @require_auth
    def route_auto_schtasks_query_detail():
        """Get detailed information about a specific scheduled task."""
        try:
            from flask import request
            task_name = request.args.get("task", "").strip()
            verbose = request.args.get("verbose", "false").lower() in ("true", "1", "yes")
        except Exception:
            task_name = ""
            verbose = False

        if not task_name:
            return _missing_field("task (query param)")

        args = ["Query", "/V", "/FO", "LIST", "/TN", task_name]
        if not verbose:
            args = ["Query", "/FO", "LIST", "/TN", task_name]

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "verbose": verbose,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks query detail timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/folders", methods=["GET"])
    @require_auth
    def route_auto_schtasks_folders():
        """List task scheduler folders."""
        try:
            stdout, stderr, rc = _run_schtasks(["Query", "/FO", "LIST", "/NH"], timeout=20)
            return jsonify({
                "ok": rc == 0,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks folders query timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/run", methods=["POST"])
    @require_auth
    def route_auto_schtasks_run():
        """Run a scheduled task immediately."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        if not task_name:
            return _missing_field("task")

        try:
            stdout, stderr, rc = _run_schtasks(["/Run", "/TN", task_name], timeout=30)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks run timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/end", methods=["POST"])
    @require_auth
    def route_auto_schtasks_end():
        """Stop a running scheduled task."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        if not task_name:
            return _missing_field("task")

        try:
            stdout, stderr, rc = _run_schtasks(["/End", "/TN", task_name], timeout=15)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks end timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/delete", methods=["POST"])
    @require_auth
    def route_auto_schtasks_delete():
        """Delete a scheduled task."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        force = body.get("force", False)

        if not task_name:
            return _missing_field("task")

        args = ["/Delete", "/TN", task_name, "/F"]
        if not force:
            args = ["/Delete", "/TN", task_name]

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "force": force,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks delete timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/create/hourly", methods=["POST"])
    @require_auth
    def route_auto_schtasks_create_hourly():
        """Create a task that runs a program every N hours."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        program = body.get("program", "").strip()
        interval = body.get("interval", 1)

        if not task_name:
            return _missing_field("task")
        if not program:
            return _missing_field("program")

        try:
            interval = int(interval)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "interval must be an integer"}), 400

        if interval < 1 or interval > 999:
            return jsonify({"ok": False, "error": "interval must be 1-999"}), 400

        args = [
            "/Create", "/SC", "HOURLY", "/MO", str(interval),
            "/TN", task_name, "/TR", program, "/F",
        ]

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "program": program,
                "interval_hours": interval,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks create timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/create/daily", methods=["POST"])
    @require_auth
    def route_auto_schtasks_create_daily():
        """Create a task that runs a program daily at a specific time."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        program = body.get("program", "").strip()
        start_time = body.get("time", "09:00").strip()
        interval_days = body.get("interval_days", 1)

        if not task_name:
            return _missing_field("task")
        if not program:
            return _missing_field("program")

        try:
            interval = int(interval_days)
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "interval_days must be an integer"}), 400

        if interval < 1 or interval > 365:
            return jsonify({"ok": False, "error": "interval_days must be 1-365"}), 400

        args = [
            "/Create", "/SC", "DAILY", "/MO", str(interval),
            "/TN", task_name, "/TR", program,
            "/ST", start_time, "/F",
        ]

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "program": program,
                "start_time": start_time,
                "interval_days": interval,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks create timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/schtasks/create/onstart", methods=["POST"])
    @require_auth
    def route_auto_schtasks_create_onstart():
        """Create a task that runs a program at system startup."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        task_name = body.get("task", "").strip()
        program = body.get("program", "").strip()
        delay = body.get("delay", "PT0M").strip()

        if not task_name:
            return _missing_field("task")
        if not program:
            return _missing_field("program")

        args = [
            "/Create", "/SC", "ONSTART",
            "/TN", task_name, "/TR", program,
            "/DELAY", delay, "/F",
        ]

        try:
            stdout, stderr, rc = _run_schtasks(args, timeout=20)
            return jsonify({
                "ok": rc == 0,
                "task_name": task_name,
                "program": program,
                "delay": delay,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "schtasks create timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
