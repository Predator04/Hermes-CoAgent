"""File, app launch, and power management routes."""
import os, subprocess, ctypes
from pathlib import Path
from flask import jsonify
from shared import _json_body, _log, _missing_field, COAGENT_DIR, _sanitize_path, _sanitize_cmd
from routes_config import backup_file

_ALLOWED_DELETE_ROOTS = {Path(_sanitize_path(str(COAGENT_DIR))).resolve()}
_HOME_DIR = Path.home().resolve()
_PROTECTED_DELETE_DIRS = {
    _HOME_DIR,
    _HOME_DIR / "Desktop",
    _HOME_DIR / "Documents",
    _HOME_DIR / "Downloads",
    _HOME_DIR / "Pictures",
    _HOME_DIR / "Music",
    _HOME_DIR / "Videos",
    Path(_sanitize_path(str(COAGENT_DIR))).resolve(),
}


def _is_protected_delete_path(path):
    resolved = Path(path).resolve()
    protected = {p.resolve() for p in _PROTECTED_DELETE_DIRS}
    return resolved in protected

def register_routes(app, state, require_auth):
    @app.route("/file/list", methods=["POST"])
    @require_auth
    def route_file_list():
        d = _json_body()
        try:
            path = _sanitize_path(d.get("path", COAGENT_DIR))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        try:
            entries = []
            for e in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    st = e.stat()
                    entries.append({"name": e.name, "path": e.path, "is_dir": e.is_dir(),
                                    "size": st.st_size, "mtime": int(st.st_mtime)})
                except Exception:
                    pass
            return jsonify({"path": path, "entries": entries, "count": len(entries)})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.route("/file/read", methods=["POST"])
    @require_auth
    def route_file_read():
        d = _json_body()
        try:
            path = _sanitize_path(d.get("path", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404
        if os.path.getsize(path) > 50 * 1024 * 1024:
            return jsonify({"error": "File too large (>50MB)"}), 413
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return jsonify({"path": path, "content": content, "size": len(content)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/file/write", methods=["POST"])
    @require_auth
    def route_file_write():
        d = _json_body()
        try:
            path = _sanitize_path(d.get("path", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        content = d.get("content", "")
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            backup_path = backup_file(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            _log(f"File written: {path} ({len(content)} chars)")
            return jsonify({"status": "ok", "path": path, "size": len(content), "backup": backup_path})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/file/delete", methods=["POST"])
    @require_auth
    def route_file_delete():
        d = _json_body()
        try:
            path = _sanitize_path(d.get("path", ""))
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        try:
            resolved = Path(path).resolve()
            if _is_protected_delete_path(resolved):
                return jsonify({"error": "Refusing to delete a protected directory", "path": str(resolved)}), 403
            if d.get("confirm") is not True:
                return jsonify({"error": "Deletion requires confirm: true", "path": str(resolved)}), 400
            backup_path = backup_file(path)
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
            _log(f"File deleted: {path}")
            return jsonify({"status": "ok", "path": path, "backup": backup_path})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/app/open", methods=["POST"])
    @require_auth
    def route_app_open():
        d = _json_body()
        app_path = d.get("path", "")
        try:
            if app_path.startswith(("http://", "https://")):
                import webbrowser
                webbrowser.open_new_tab(app_path)
            elif ("/" not in app_path and "\\" not in app_path and ":" not in app_path
                  and app_path.lower().endswith(".exe")):
                subprocess.Popen([app_path], shell=False)
            elif app_path.endswith(".lnk") or app_path.endswith(".exe"):
                safe_path = _sanitize_path(app_path)
                subprocess.Popen([safe_path], shell=False)
            else:
                os.startfile(_sanitize_path(app_path))
            _log(f"App launched: {app_path}")
            return jsonify({"status": "launched", "app": app_path})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/app/run", methods=["POST"])
    @require_auth
    def route_app_run():
        d = _json_body()
        cmd = d.get("cmd", d.get("command", ""))
        if not cmd:
            return _missing_field("cmd or command")
        try:
            safe_cmd = _sanitize_cmd(cmd)
            r = subprocess.run(safe_cmd, capture_output=True, text=True, timeout=30)
            return jsonify({"status": "ok", "stdout": r.stdout[:10000], "stderr": r.stderr[:5000], "returncode": r.returncode})
        except ValueError as e:
            return jsonify({"error": str(e)}), 403
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Command timed out"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/power/sleep", methods=["POST"])
    @require_auth
    def route_power_sleep():
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], timeout=5)
        return jsonify({"status": "sleeping"})

    @app.route("/power/shutdown", methods=["POST"])
    @require_auth
    def route_power_shutdown():
        subprocess.run(["shutdown", "/s", "/t", "10"], timeout=5)
        return jsonify({"status": "shutdown", "timeout": 10})

    @app.route("/power/restart", methods=["POST"])
    @require_auth
    def route_power_restart():
        subprocess.run(["shutdown", "/r", "/t", "10"], timeout=5)
        return jsonify({"status": "restart", "timeout": 10})

    @app.route("/power/lock", methods=["POST"])
    @require_auth
    def route_power_lock():
        ctypes.windll.user32.LockWorkStation()
        return jsonify({"status": "locked"})

    @app.route("/power/cancel", methods=["POST"])
    @require_auth
    def route_power_cancel():
        subprocess.run(["shutdown", "/a"], timeout=5)
        return jsonify({"status": "cancelled"})
