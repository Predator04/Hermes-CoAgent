"""Git backup, commit, push, and rollback routes."""

import json
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log


_LOCK = threading.RLock()
_FILE_LOCK = threading.Lock()
_AUTO_ENABLED = False
_AUTO_THREAD = None
_AUTO_INTERVAL_SECONDS = 1800
_LAST_COMMIT = None
_LAST_PUSH_TIME = None
_LAST_ERROR = None
_BACKUP_ROOT = COAGENT_DIR / "backups" / "git"
_HASH_RE = re.compile(r"^[A-Fa-f0-9]{4,64}$")


def _file_busy_payload():
    return {"status": "busy", "error": "Git file operation already in progress"}, 409


def _run_git(args, timeout=120):
    cmd = ["git", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(COAGENT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "args": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
    except FileNotFoundError:
        return {"args": cmd, "returncode": None, "stdout": "", "stderr": "git.exe not found in PATH", "ok": False}
    except subprocess.TimeoutExpired as e:
        return {"args": cmd, "returncode": None, "stdout": e.stdout or "", "stderr": "git command timed out", "ok": False}


def _is_no_changes(result):
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
    return "nothing to commit" in text or "no changes added to commit" in text


def _ensure_token_gitignored():
    ignore_path = COAGENT_DIR / ".gitignore"
    required = [".token", ".token_*"]
    if ignore_path.exists():
        text = ignore_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
    else:
        text = ""
        lines = []
    present = {line.strip() for line in lines}
    missing = [entry for entry in required if entry not in present]
    if missing:
        prefix = "" if not text or text.endswith(("\n", "\r")) else "\n"
        ignore_path.write_text(text + prefix + "\n".join(missing) + "\n", encoding="utf-8")
    return {"path": str(ignore_path), "added": missing}


def _commit(message=None):
    global _LAST_COMMIT, _LAST_ERROR
    if not _FILE_LOCK.acquire(blocking=False):
        return _file_busy_payload()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = str(message).strip() if message else f"auto: {stamp}"
    try:
        try:
            gitignore_result = _ensure_token_gitignored()
        except Exception as e:
            error = {"error": str(e), "type": type(e).__name__}
            with _LOCK:
                _LAST_ERROR = error
            return {"status": "gitignore_failed", "gitignore": error}, 500
        add_result = _run_git(["add", "."], timeout=120)
        if not add_result["ok"]:
            with _LOCK:
                _LAST_ERROR = add_result
            return {"status": "add_failed", "gitignore": gitignore_result, "add": add_result}, 500
        commit_result = _run_git(["commit", "-m", message], timeout=120)
        if commit_result["ok"]:
            with _LOCK:
                _LAST_COMMIT = {"message": message, "time": time.time(), "result": commit_result}
                _LAST_ERROR = None
            return {"status": "committed", "message": message, "gitignore": gitignore_result, "add": add_result, "commit": commit_result}, 200
        if _is_no_changes(commit_result):
            return {"status": "no_changes", "message": message, "gitignore": gitignore_result, "add": add_result, "commit": commit_result}, 200
        with _LOCK:
            _LAST_ERROR = commit_result
        return {"status": "commit_failed", "message": message, "gitignore": gitignore_result, "add": add_result, "commit": commit_result}, 500
    finally:
        _FILE_LOCK.release()


def _auto_loop():
    global _AUTO_ENABLED
    while True:
        with _LOCK:
            enabled = _AUTO_ENABLED
            interval = _AUTO_INTERVAL_SECONDS
        if not enabled:
            return
        try:
            _commit()
        except Exception as e:
            with _LOCK:
                globals()["_LAST_ERROR"] = f"{type(e).__name__}: {e}"
            _log(f"Git auto-commit failed: {type(e).__name__}: {e}")
        slept = 0
        while slept < interval:
            time.sleep(min(5, interval - slept))
            slept += min(5, interval - slept)
            with _LOCK:
                if not _AUTO_ENABLED:
                    return


def _status_lines():
    result = _run_git(["status", "--short"], timeout=30)
    if not result["ok"]:
        return result, []
    return result, [line for line in result["stdout"].splitlines() if line.strip()]


def _last_commit_info():
    result = _run_git(["log", "-1", "--pretty=format:%H%x09%an%x09%ad%x09%s", "--date=iso-strict"], timeout=30)
    if not result["ok"] or not result["stdout"].strip():
        return None
    parts = result["stdout"].split("\t", 3)
    while len(parts) < 4:
        parts.append("")
    return {"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]}


def _changed_paths():
    _result, lines = _status_lines()
    paths = []
    for line in lines:
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            paths.append(path.strip('"'))
    return paths


def _redact_env(src, dst):
    redacted = []
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            redacted.append(line)
            continue
        key, _value = line.split("=", 1)
        redacted.append(f"{key}=<redacted>")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(redacted) + "\n", encoding="utf-8")


def _copy_file(src, backup_dir):
    rel = src.resolve().relative_to(COAGENT_DIR)
    dst = backup_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _copy_tree(src, backup_dir):
    rel = src.resolve().relative_to(COAGENT_DIR)
    dst = backup_dir / rel
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return str(dst)


def _make_backup():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    config = COAGENT_DIR / "config.json"
    if config.exists() and config.is_file():
        copied.append(_copy_file(config, backup_dir))
    env_file = COAGENT_DIR / ".env"
    if env_file.exists() and env_file.is_file():
        dst = backup_dir / ".env.redacted"
        _redact_env(env_file, dst)
        copied.append(str(dst))
    recordings = COAGENT_DIR / "recordings"
    if recordings.exists() and recordings.is_dir():
        copied.append(_copy_tree(recordings, backup_dir))
    for rel in _changed_paths():
        if not (rel.startswith("routes_") or rel == "hermes_coagent.py"):
            continue
        src = (COAGENT_DIR / rel).resolve()
        try:
            src.relative_to(COAGENT_DIR)
        except ValueError:
            continue
        if src.exists() and src.is_file():
            copied.append(_copy_file(src, backup_dir))
    manifest = {
        "created_at": time.time(),
        "backup_dir": str(backup_dir),
        "copied": copied,
        "changed_paths": _changed_paths(),
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def register_routes(app, state, require_auth):
    @app.route("/git/status", methods=["GET"])
    @require_auth
    def route_git_status():
        status_result, lines = _status_lines()
        with _LOCK:
            auto = {
                "enabled": _AUTO_ENABLED,
                "interval_seconds": _AUTO_INTERVAL_SECONDS,
                "thread_alive": bool(_AUTO_THREAD and _AUTO_THREAD.is_alive()),
                "last_commit": _LAST_COMMIT,
                "last_push_time": _LAST_PUSH_TIME,
                "last_error": _LAST_ERROR,
            }
        return jsonify({
            "git_available": status_result["ok"] or status_result["returncode"] != 9009,
            "dirty": bool(lines),
            "dirty_files": lines,
            "status": status_result,
            "last_commit": _last_commit_info(),
            "auto": auto,
        })

    @app.route("/git/commit", methods=["POST"])
    @require_auth
    def route_git_commit():
        data = _json_body()
        payload, status = _commit(data.get("message"))
        return jsonify(payload), status

    @app.route("/git/push", methods=["POST"])
    @require_auth
    def route_git_push():
        global _LAST_PUSH_TIME, _LAST_ERROR
        data = _json_body()
        remote = str(data.get("remote", "origin") or "origin")
        branch = str(data.get("branch", "main") or "main")
        result = _run_git(["push", remote, branch], timeout=300)
        if result["ok"]:
            with _LOCK:
                _LAST_PUSH_TIME = time.time()
                _LAST_ERROR = None
            return jsonify({"status": "pushed", "remote": remote, "branch": branch, "result": result})
        with _LOCK:
            _LAST_ERROR = result
        return jsonify({"status": "push_failed", "remote": remote, "branch": branch, "result": result}), 500

    @app.route("/git/auto", methods=["POST"])
    @require_auth
    def route_git_auto():
        global _AUTO_ENABLED, _AUTO_THREAD, _AUTO_INTERVAL_SECONDS
        data = _json_body()
        enabled = bool(data.get("enabled", True))
        interval_minutes = float(data.get("interval_minutes", 30) or 30)
        interval_seconds = max(60, min(int(interval_minutes * 60), 24 * 3600))
        with _LOCK:
            _AUTO_ENABLED = enabled
            _AUTO_INTERVAL_SECONDS = interval_seconds
            if enabled and not (_AUTO_THREAD and _AUTO_THREAD.is_alive()):
                _AUTO_THREAD = threading.Thread(target=_auto_loop, name="git_auto_commit", daemon=True)
                _AUTO_THREAD.start()
            thread_alive = bool(_AUTO_THREAD and _AUTO_THREAD.is_alive())
        return jsonify({"status": "enabled" if enabled else "disabled", "interval_seconds": interval_seconds, "thread_alive": thread_alive})

    @app.route("/git/backup", methods=["POST"])
    @require_auth
    def route_git_backup():
        if not _FILE_LOCK.acquire(blocking=False):
            payload, status = _file_busy_payload()
            return jsonify(payload), status
        try:
            manifest = _make_backup()
            return jsonify({"status": "backed_up", **manifest})
        except Exception as e:
            return jsonify({"error": str(e), "type": type(e).__name__}), 500
        finally:
            _FILE_LOCK.release()

    @app.route("/git/rollback/<hash_value>", methods=["POST"])
    @require_auth
    def route_git_rollback(hash_value):
        data = _json_body()
        if not _HASH_RE.match(hash_value):
            return jsonify({"error": "hash must be a git revision hash"}), 400
        _status_result, dirty = _status_lines()
        if dirty and not data.get("allow_dirty"):
            return jsonify({"error": "working tree is dirty; pass allow_dirty=true to revert anyway", "dirty_files": dirty}), 409
        args = ["revert", hash_value]
        if data.get("no_edit", True):
            args.insert(1, "--no-edit")
        result = _run_git(args, timeout=300)
        if result["ok"]:
            return jsonify({"status": "reverted", "hash": hash_value, "result": result})
        return jsonify({"status": "revert_failed", "hash": hash_value, "result": result}), 500
