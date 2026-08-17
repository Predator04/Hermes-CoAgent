# Auto-added feature: LGUG2Z/komorebi (14864 stars)
# Description: A tiling window manager for Windows
# Source: https://github.com/LGUG2Z/komorebi

import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "LGUG2Z/komorebi",
    "stars": 14864,
    "desc": "A tiling window manager for Windows — manage window layouts, workspaces, focus, and tiling state via komorebic CLI",
    "url": "https://github.com/LGUG2Z/komorebi",
    "added": "2026-07-05",
    "command": "komorebic <subcommand>",
}


def _find_komorebic():
    return shutil.which("komorebic") or shutil.which("komorebic.exe")


def _clean_action(value):
    action = str(value or "").strip().lower()
    if not action:
        raise ValueError("action must not be empty")
    if "\x00" in action:
        raise ValueError("action cannot contain null bytes")
    if action.startswith("-"):
        raise ValueError("action cannot start with '-'")
    if not action.replace("-", "").replace("_", "").isalnum():
        raise ValueError("action contains invalid characters")
    return action


def _clean_count(value):
    try:
        c = int(value) if value is not None else 1
    except (TypeError, ValueError):
        raise ValueError("count must be an integer")
    return max(1, min(c, 50))


def _is_komorebi_running():
    """Check if komorebi (the window manager) is running by probing komorebic state."""
    exe = _find_komorebic()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "state"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def register_routes(app, state, require_auth):
    @app.route("/auto/komorebi/info", methods=["GET"])
    @require_auth
    def route_auto_komorebi_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/komorebi/ping", methods=["GET"])
    @require_auth
    def route_auto_komorebi_ping():
        exe = _find_komorebic()
        running = _is_komorebi_running() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "LGUG2Z/komorebi",
            "available": bool(exe),
            "running": running,
            "command": exe or "komorebic",
        })

    @app.route("/auto/komorebi/state", methods=["GET"])
    @require_auth
    def route_auto_komorebi_state():
        exe = _find_komorebic()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "komorebic command not found on PATH",
                "hint": "Install komorebi from https://github.com/LGUG2Z/komorebi",
            }), 503

        try:
            result = subprocess.run(
                [exe, "state"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except OSError as exc:
            _log(f"[komorebi] state failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "komorebic state timed out"}), 504

        ok = result.returncode == 0
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502

    @app.route("/auto/komorebi/command", methods=["POST"])
    @require_auth
    def route_auto_komorebi_command():
        data = _json_body()
        missing = _missing_field(data, "action")
        if missing:
            return missing

        exe = _find_komorebic()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "komorebic command not found on PATH",
                "hint": "Install komorebi from https://github.com/LGUG2Z/komorebi",
            }), 503

        try:
            action = _clean_action(data.get("action"))
            count = _clean_count(data.get("count"))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        command = [exe, action]
        # Some actions take a count or target parameter
        extras = data.get("args")
        if extras:
            if not isinstance(extras, list):
                return jsonify({"ok": False, "error": "args must be a list"}), 400
            for arg in extras:
                s = str(arg)
                if s.startswith("-") or "\x00" in s:
                    return jsonify({"ok": False, "error": f"invalid arg: {s!r}"}), 400
                command.append(s)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[komorebi] command timed out after 15s action={action}")
            return jsonify({
                "ok": False,
                "error": f"komorebic command timed out after 15s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[komorebi] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[komorebi] action={action} exit={result.returncode}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "action": action,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502

    @app.route("/auto/komorebi/workspace", methods=["POST"])
    @require_auth
    def route_auto_komorebi_workspace():
        data = _json_body()
        missing = _missing_field(data, "workspace")
        if missing:
            return missing

        exe = _find_komorebic()
        if not exe:
            return jsonify({
                "ok": False,
                "error": "komorebic command not found on PATH",
                "hint": "Install komorebi from https://github.com/LGUG2Z/komorebi",
            }), 503

        try:
            workspace = int(data.get("workspace", 0))
            if workspace < 0 or workspace > 9:
                raise ValueError("workspace must be 0-9")
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        subcommand = (data.get("subcommand") or "focus").strip().lower()
        if subcommand not in ("focus", "move"):
            return jsonify({
                "ok": False,
                "error": "subcommand must be 'focus' or 'move'",
            }), 400

        # komorebic uses hyphenated subcommands (focus-workspace / move-to-workspace),
        # and workspace indices are zero-based.
        cmd_subcommand = "focus-workspace" if subcommand == "focus" else "move-to-workspace"
        command = [exe, cmd_subcommand, str(workspace)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "workspace command timed out"}), 504
        except OSError as exc:
            _log(f"[komorebi] workspace failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[komorebi] workspace subcommand={subcommand} workspace={workspace} exit={result.returncode}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "subcommand": subcommand,
            "workspace": workspace,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
