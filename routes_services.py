"""Windows service and scheduled task management routes.

Endpoints:
  GET  /services/list      - enumerate Windows services (name, display, state)
  POST /services/status    - inspect a single service by name
  POST /services/start     - start a service
  POST /services/stop      - stop a service
  POST /services/restart   - stop then start a service

  GET  /tasks/list         - list scheduled tasks
  POST /tasks/status       - inspect a single scheduled task
  POST /tasks/run          - trigger a scheduled task
  POST /tasks/end          - stop a running task instance
  POST /tasks/enable       - enable a scheduled task
  POST /tasks/disable      - disable a scheduled task

Uses sc.exe / schtasks.exe with ASCII-only argument strings. On non-Windows
hosts the endpoints return HTTP 501 rather than raising at import time so the
Linux syntax-check CI stays green.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field


# Service names: alphanumerics, dot, dash, underscore. Max 256 per Windows docs.
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,256}$")
# Task paths: allow backslash + forward slash for subfolders (e.g. \Microsoft\Windows\...).
_TASK_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-\\/ ]{1,512}$")

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_exe(name):
    hit = shutil.which(name) or shutil.which(f"{name}.exe")
    if hit:
        return hit
    for base in (r"C:\Windows\System32", r"C:\Windows\SysWOW64"):
        candidate = os.path.join(base, f"{name}.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def _run(cmd, timeout=15):
    """Run a subprocess and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _valid_service_name(name):
    return isinstance(name, str) and bool(_SERVICE_NAME_RE.fullmatch(name))


def _valid_task_name(name):
    return isinstance(name, str) and bool(_TASK_NAME_RE.fullmatch(name))


def _parse_sc_query(text):
    """Parse sc.exe query output into a list of dicts."""
    services = []
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            if current:
                services.append(current)
                current = None
            continue
        if line.upper().startswith("SERVICE_NAME:"):
            if current:
                services.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
            continue
        if current is None:
            continue
        if line.upper().startswith("DISPLAY_NAME:"):
            current["display_name"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("STATE"):
            # STATE              : 4  RUNNING
            parts = line.split(":", 1)
            if len(parts) == 2:
                tokens = parts[1].split()
                if tokens:
                    current["state_code"] = tokens[0]
                    current["state"] = tokens[1] if len(tokens) > 1 else ""
        elif line.upper().startswith("TYPE"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                current["type"] = parts[1].strip()
    if current:
        services.append(current)
    return services


def _sc_query_all(sc_exe, state_filter="all"):
    text_parts = []
    # sc query returns paginated output; use bufsize= to grab all in one call
    out, err, rc = _run([sc_exe, "query", "type=", "service", "state=", state_filter, "bufsize=", "262144"], timeout=25)
    text_parts.append(out)
    if rc != 0 and err:
        return [], err, rc
    return _parse_sc_query("\n".join(text_parts)), "", 0


def _sc_query_one(sc_exe, name):
    out, err, rc = _run([sc_exe, "query", name], timeout=10)
    if rc != 0:
        return None, err or out, rc
    services = _parse_sc_query(out)
    return (services[0] if services else None), "", 0


def _parse_schtasks_csv(text):
    """Parse schtasks /query /fo CSV /v output. Returns list of dicts."""
    if not text:
        return []
    # Some Windows locales prepend a BOM or blank lines; strip them.
    buf = io.StringIO(text.lstrip("﻿"))
    reader = csv.reader(buf)
    rows = [row for row in reader if row]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    tasks = []
    for row in rows[1:]:
        # /v output repeats the header row occasionally between folders; skip.
        if row == rows[0]:
            continue
        if len(row) != len(header):
            continue
        entry = dict(zip(header, [c.strip() for c in row]))
        # Preserve raw fields but promote the common ones.
        tasks.append({
            "task_name": entry.get("TaskName", ""),
            "status": entry.get("Status", ""),
            "next_run": entry.get("Next Run Time", ""),
            "last_run": entry.get("Last Run Time", ""),
            "last_result": entry.get("Last Result", ""),
            "author": entry.get("Author", ""),
            "run_as": entry.get("Run As User", ""),
            "schedule": entry.get("Schedule Type", ""),
            "raw": entry,
        })
    return tasks


def register_routes(app, state, require_auth):
    sc_exe = _find_exe("sc")
    schtasks_exe = _find_exe("schtasks")

    # -- Services ----------------------------------------------------------

    @app.route("/services/list", methods=["GET", "POST"])
    @require_auth
    def route_services_list():
        if os.name != "nt" or not sc_exe:
            return _windows_only()
        state_filter = "all"
        body = _json_body()
        if isinstance(body, dict):
            requested = str(body.get("state", "all")).lower()
            if requested in {"all", "active", "inactive"}:
                state_filter = requested
        services, err, rc = _sc_query_all(sc_exe, state_filter)
        if rc != 0:
            return jsonify({"error": err or "sc.exe failed", "returncode": rc}), 500
        return jsonify({
            "services": services,
            "count": len(services),
            "state_filter": state_filter,
        })

    @app.route("/services/status", methods=["POST"])
    @require_auth
    def route_services_status():
        if os.name != "nt" or not sc_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_service_name(name):
            return jsonify({"error": "invalid service name"}), 400
        service, err, rc = _sc_query_one(sc_exe, name)
        if rc != 0 or not service:
            return jsonify({"error": err or "service not found", "name": name, "returncode": rc}), 404
        return jsonify({"service": service})

    def _service_control(action, name, timeout=20):
        cmd = [sc_exe, action, name]
        out, err, rc = _run(cmd, timeout=timeout)
        return {"stdout": out.strip(), "stderr": err.strip(), "returncode": rc}

    @app.route("/services/start", methods=["POST"])
    @require_auth
    def route_services_start():
        if os.name != "nt" or not sc_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_service_name(name):
            return jsonify({"error": "invalid service name"}), 400
        result = _service_control("start", name)
        _log(f"services/start {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status

    @app.route("/services/stop", methods=["POST"])
    @require_auth
    def route_services_stop():
        if os.name != "nt" or not sc_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_service_name(name):
            return jsonify({"error": "invalid service name"}), 400
        result = _service_control("stop", name)
        _log(f"services/stop {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status

    @app.route("/services/restart", methods=["POST"])
    @require_auth
    def route_services_restart():
        if os.name != "nt" or not sc_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_service_name(name):
            return jsonify({"error": "invalid service name"}), 400
        try:
            wait_seconds = float(body.get("wait", 10))
        except (TypeError, ValueError):
            wait_seconds = 10.0
        wait_seconds = max(0.0, min(wait_seconds, 60.0))

        stop_result = _service_control("stop", name)
        # Poll the state until it reaches STOPPED or the deadline expires.
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            svc, _err, rc = _sc_query_one(sc_exe, name)
            if rc == 0 and svc and svc.get("state", "").upper() == "STOPPED":
                break
            time.sleep(0.5)
        start_result = _service_control("start", name)
        _log(f"services/restart {name} stop_rc={stop_result['returncode']} start_rc={start_result['returncode']}")
        overall_ok = start_result["returncode"] == 0
        return jsonify({
            "status": "ok" if overall_ok else "error",
            "name": name,
            "stop": stop_result,
            "start": start_result,
        }), (200 if overall_ok else 500)

    # -- Scheduled tasks ---------------------------------------------------

    @app.route("/tasks/list", methods=["GET", "POST"])
    @require_auth
    def route_tasks_list():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        folder = None
        if isinstance(body, dict):
            requested = body.get("folder")
            if isinstance(requested, str) and requested.strip():
                if not _valid_task_name(requested.strip()):
                    return jsonify({"error": "invalid folder path"}), 400
                folder = requested.strip()
        cmd = [schtasks_exe, "/query", "/fo", "CSV", "/v"]
        if folder:
            cmd.extend(["/tn", folder])
        out, err, rc = _run(cmd, timeout=45)
        if rc != 0:
            return jsonify({"error": err.strip() or out.strip() or "schtasks failed",
                            "returncode": rc}), 500
        tasks = _parse_schtasks_csv(out)
        return jsonify({"tasks": tasks, "count": len(tasks), "folder": folder})

    def _task_control(action_flag, name, extra=None, timeout=20):
        cmd = [schtasks_exe, action_flag, "/tn", name]
        if extra:
            cmd.extend(extra)
        out, err, rc = _run(cmd, timeout=timeout)
        return {"stdout": out.strip(), "stderr": err.strip(), "returncode": rc}

    @app.route("/tasks/status", methods=["POST"])
    @require_auth
    def route_tasks_status():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_task_name(name):
            return jsonify({"error": "invalid task name"}), 400
        out, err, rc = _run([schtasks_exe, "/query", "/tn", name, "/fo", "CSV", "/v"], timeout=15)
        if rc != 0:
            return jsonify({"error": err.strip() or out.strip() or "task not found",
                            "name": name, "returncode": rc}), 404
        tasks = _parse_schtasks_csv(out)
        return jsonify({"task": tasks[0] if tasks else None, "matches": tasks})

    @app.route("/tasks/run", methods=["POST"])
    @require_auth
    def route_tasks_run():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_task_name(name):
            return jsonify({"error": "invalid task name"}), 400
        result = _task_control("/run", name)
        _log(f"tasks/run {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status

    @app.route("/tasks/end", methods=["POST"])
    @require_auth
    def route_tasks_end():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_task_name(name):
            return jsonify({"error": "invalid task name"}), 400
        result = _task_control("/end", name)
        _log(f"tasks/end {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status

    @app.route("/tasks/enable", methods=["POST"])
    @require_auth
    def route_tasks_enable():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_task_name(name):
            return jsonify({"error": "invalid task name"}), 400
        result = _task_control("/change", name, extra=["/enable"])
        _log(f"tasks/enable {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status

    @app.route("/tasks/disable", methods=["POST"])
    @require_auth
    def route_tasks_disable():
        if os.name != "nt" or not schtasks_exe:
            return _windows_only()
        body = _json_body()
        name = body.get("name", "") if isinstance(body, dict) else ""
        if not name:
            return _missing_field("name")
        if not _valid_task_name(name):
            return jsonify({"error": "invalid task name"}), 400
        result = _task_control("/change", name, extra=["/disable"])
        _log(f"tasks/disable {name} rc={result['returncode']}")
        status = 200 if result["returncode"] == 0 else 500
        return jsonify({"status": "ok" if result["returncode"] == 0 else "error",
                        "name": name, **result}), status
