"""Native Windows Scheduled Task persistence for recipes.

Endpoints:
  POST   /scheduler/tasks          - export a recipe to a real Windows
                                     Scheduled Task (survives reboot / runs
                                     even when the CoAgent server is closed).
                                     Body: {recipe_id, trigger, time, name}
  GET    /scheduler/tasks          - list CoAgent-persisted recipe tasks
  POST   /scheduler/tasks/<name>/run - run a persisted task immediately
  DELETE /scheduler/tasks/<name>   - remove a persisted task

How it works:
  - A strict, ASCII-only recipe id is mapped to a task named
    "CoAgent-Recipe-<id>". The task action points at a small generated
    launcher (COAGENT_DIR/scheduler/run_recipe_<id>.bat) that POSTs to the
    local recipe run endpoint, so the recipe logic stays in CoAgent while the
    *schedule* lives in Task Scheduler.
  - schtasks is invoked via subprocess with a list argv (never shell=True),
    and both the recipe id and task name are validated against a narrow regex
    to prevent command injection (the repo has previously fixed schtasks
    injection issues - see routes_uac.py / routes_onboarding.py).
  - Non-Windows hosts return HTTP 501 instead of failing at import time so the
    Linux syntax-check CI stays green.
"""

import json
import os
import re
import shutil
import subprocess

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field, _self_port

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Recipe ids are generated/validated by routes_recipes as uuid hex or the
# caller's own id; we accept only a conservative ASCII-safe shape.
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Persisted task names are always CoAgent-Recipe-<id>, so delete/run accept
# only that exact pattern.
_TASK_NAME_RE = re.compile(r"^CoAgent-Recipe-[A-Za-z0-9_.-]{1,64}$")

_TRIGGERS = {
    "once": ("ONCE", True),
    "daily": ("DAILY", True),
    "hourly": ("HOURLY", False),
    "onlogon": ("ONLOGON", False),
    "onstart": ("ONSTART", False),
    "onidle": ("ONIDLE", False),
}

_RECIPES_FILE = COAGENT_DIR / "recipes.json"
_SCHED_DIR = COAGENT_DIR / "scheduler"


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_schtasks():
    return shutil.which("schtasks") or shutil.which("schtasks.exe") \
        or r"C:\Windows\System32\schtasks.exe"


def _run_schtasks(args, timeout=20):
    """Run schtasks with a list argv. Returns (stdout, stderr, returncode)."""
    exe = _find_schtasks()
    if not exe or not os.path.isfile(exe):
        return "", "schtasks.exe not found", -1
    try:
        r = subprocess.run(
            [exe] + args,
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _validate_time(value):
    """Return a normalized HH:MM or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not re.fullmatch(r"^(?:[01]\d|2[0-3]):[0-5]\d$", value):
        return None
    return value


def _recipe_exists(recipe_id):
    """Return the recipe name if the id exists in recipes.json, else None."""
    try:
        if not _RECIPES_FILE.exists():
            return None
        data = json.loads(_RECIPES_FILE.read_text(encoding="utf-8"))
        recipes = data.get("recipes", data) if isinstance(data, dict) else {}
        recipe = recipes.get(recipe_id) if isinstance(recipes, dict) else None
        if isinstance(recipe, dict):
            return str(recipe.get("name") or recipe_id)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def _write_launcher(recipe_id):
    """Generate a launcher .bat that runs the recipe via the local API."""
    _SCHED_DIR.mkdir(parents=True, exist_ok=True)
    launcher = _SCHED_DIR / f"run_recipe_{recipe_id}.bat"
    port = _self_port()
    token_file = str(COAGENT_DIR / ".token")
    # Pure-ASCII batch. curl.exe ships with Windows 10 1803+.
    content = (
        "@echo off\r\n"
        f"rem CoAgent scheduled-recipe launcher for recipe {recipe_id} (auto-generated)\r\n"
        "setlocal\r\n"
        f'set "TOKEN_FILE={token_file}"\r\n'
        'set "TOKEN="\r\n'
        'if exist "%TOKEN_FILE%" set /p TOKEN=<"%TOKEN_FILE%"\r\n'
        f'set "URL=http://127.0.0.1:{port}/recipes/run/{recipe_id}"\r\n'
        "if defined TOKEN (\r\n"
        "  curl.exe -s -X POST -H \"Authorization: Bearer %TOKEN%\" \"%URL%\"\r\n"
        ") else (\r\n"
        "  curl.exe -s -X POST \"%URL%\"\r\n"
        ")\r\n"
        "endlocal\r\n"
    )
    launcher.write_text(content, encoding="ascii")
    return launcher


def _build_create_args(recipe_id, trigger, time_value, launcher):
    args = [
        "/Create", "/TN", f"CoAgent-Recipe-{recipe_id}",
        "/TR", f'"{launcher}"',
        "/SC", _TRIGGERS[trigger][0],
    ]
    if _TRIGGERS[trigger][1]:
        args += ["/ST", time_value or "09:00"]
    args += ["/F"]
    return args


def register_routes(app, state, require_auth):
    @app.route("/scheduler/tasks", methods=["POST"])
    @require_auth
    def route_scheduler_tasks_create():
        if os.name != "nt":
            return _windows_only()
        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        recipe_id = str(body.get("recipe_id") or body.get("recipe") or "").strip()
        if not _ID_RE.match(recipe_id):
            return jsonify({"error": "invalid recipe_id (allowed: A-Za-z0-9_.-, max 64)"}), 400

        trigger = str(body.get("trigger") or "once").strip().lower()
        if trigger not in _TRIGGERS:
            return jsonify({
                "error": f"invalid trigger; allowed: {', '.join(_TRIGGERS)}",
            }), 400

        time_value = None
        if _TRIGGERS[trigger][1]:
            time_value = _validate_time(body.get("time"))
            if time_value is None:
                return jsonify({"error": "time is required as HH:MM for this trigger"}), 400

        recipe_name = _recipe_exists(recipe_id)
        if recipe_name is None:
            return jsonify({"error": "recipe not found", "recipe_id": recipe_id}), 404

        try:
            launcher = _write_launcher(recipe_id)
        except (OSError, UnicodeError) as exc:
            return jsonify({"error": f"failed to write launcher: {exc}"}), 500

        args = _build_create_args(recipe_id, trigger, time_value, str(launcher))
        out, err, rc = _run_schtasks(args)
        ok = rc == 0
        _log(f"scheduler/create recipe={recipe_id} trigger={trigger} rc={rc}")
        return jsonify({
            "status": "ok" if ok else "error",
            "task_name": f"CoAgent-Recipe-{recipe_id}",
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "trigger": trigger,
            "time": time_value,
            "launcher": str(launcher),
            "stdout": out.strip(),
            "stderr": err.strip(),
            "returncode": rc,
        }), (200 if ok else 500)

    @app.route("/scheduler/tasks", methods=["GET"])
    @require_auth
    def route_scheduler_tasks_list():
        if os.name != "nt":
            return _windows_only()
        out, err, rc = _run_schtasks(["/Query", "/FO", "CSV", "/NH"])
        tasks = []
        if rc == 0:
            for line in (out or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                # CSV columns: TaskName,NextRunTime,Status
                parts = [p.strip('"') for p in line.split('","')]
                name = parts[0].strip('"') if parts else line
                # schtasks /FO CSV emits a leading backslash on root-folder task
                # names (e.g. "\CoAgent-Recipe-abc"); strip it before matching.
                name = name.lstrip("\\")
                if name.startswith("CoAgent-Recipe-"):
                    tasks.append({
                        "task_name": name,
                        "next_run": parts[1] if len(parts) > 1 else "",
                        "status": parts[2] if len(parts) > 2 else "",
                    })
        _log(f"scheduler/list count={len(tasks)} rc={rc}")
        return jsonify({"tasks": tasks, "count": len(tasks)})

    @app.route("/scheduler/tasks/<name>/run", methods=["POST"])
    @require_auth
    def route_scheduler_tasks_run(name):
        if os.name != "nt":
            return _windows_only()
        if not _TASK_NAME_RE.match(name):
            return jsonify({"error": "invalid task name"}), 400
        out, err, rc = _run_schtasks(["/Run", "/TN", name])
        _log(f"scheduler/run task={name} rc={rc}")
        return jsonify({
            "status": "ok" if rc == 0 else "error",
            "task_name": name,
            "stdout": out.strip(),
            "stderr": err.strip(),
            "returncode": rc,
        }), (200 if rc == 0 else 500)

    @app.route("/scheduler/tasks/<name>", methods=["DELETE"])
    @require_auth
    def route_scheduler_tasks_delete(name):
        if os.name != "nt":
            return _windows_only()
        if not _TASK_NAME_RE.match(name):
            return jsonify({"error": "invalid task name"}), 400
        out, err, rc = _run_schtasks(["/Delete", "/TN", name, "/F"])
        # Also remove the generated launcher for tidiness — but only when the
        # task was actually deleted; otherwise the still-scheduled task would
        # point at a missing launcher and silently no-op on every future fire.
        if rc == 0:
            recipe_id = name[len("CoAgent-Recipe-"):]
            launcher = _SCHED_DIR / f"run_recipe_{recipe_id}.bat"
            try:
                if launcher.exists():
                    launcher.unlink()
            except OSError:
                pass
        _log(f"scheduler/delete task={name} rc={rc}")
        return jsonify({
            "status": "ok" if rc == 0 else "error",
            "task_name": name,
            "stdout": out.strip(),
            "stderr": err.strip(),
            "returncode": rc,
        }), (200 if rc == 0 else 500)
