"""Config backup and rollback routes."""

import shutil
import time
from pathlib import Path

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import COAGENT_DIR, _sanitize_path


config_bp = Blueprint("config", __name__)
BACKUP_DIR = COAGENT_DIR / "backups"
MAX_BACKUPS_PER_FILE = 20


def _error(message: str, status: int = 400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _backup_name(path: Path, timestamp=None):
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    return f"{path.name}.{stamp}.bak"


def _prune_backups_for(path: Path):
    backups = sorted(
        BACKUP_DIR.glob(f"{path.name}.*.bak"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )
    for old in backups[MAX_BACKUPS_PER_FILE:]:
        try:
            old.unlink()
        except OSError:
            pass


def backup_file(path):
    """Back up a single existing file and keep only the latest 20 backups."""
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / _backup_name(target)
    suffix = 1
    while backup_path.exists():
        backup_path = BACKUP_DIR / f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}.{suffix}.bak"
        suffix += 1
    shutil.copy2(target, backup_path)
    _prune_backups_for(target)
    return str(backup_path)


def _list_backups():
    backups = []
    if not BACKUP_DIR.exists():
        return backups
    for item in sorted(BACKUP_DIR.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = item.stat()
            original = item.name.rsplit(".", 2)[0] if item.name.count(".") >= 2 else item.name
            backups.append({
                "backup": item.name,
                "path": str(item),
                "file": original,
                "size": stat.st_size,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
            })
        except OSError:
            continue
    return backups


@config_bp.route("/config/backups", methods=["GET"])
def route_config_backups():
    backups = _list_backups()
    return jsonify({"backups": backups, "count": len(backups), "backup_dir": str(BACKUP_DIR)})


@config_bp.route("/config/backup", methods=["POST"])
def route_config_backup():
    data = _json_payload()
    path = data.get("path")
    if not isinstance(path, str) or not path:
        return _error("path is required")
    try:
        safe_path = _sanitize_path(path)
    except ValueError as e:
        return _error(str(e), 403)
    backup_path = backup_file(safe_path)
    if not backup_path:
        return _error("File not found or not a regular file", 404)
    return jsonify({"status": "backed_up", "path": safe_path, "backup": backup_path})


@config_bp.route("/config/rollback", methods=["POST"])
def route_config_rollback():
    data = _json_payload()
    file_path = data.get("file")
    backup_name = data.get("backup")
    if not isinstance(file_path, str) or not file_path:
        return _error("file is required")
    if not isinstance(backup_name, str) or not backup_name:
        return _error("backup is required")
    try:
        safe_path = Path(_sanitize_path(file_path)).resolve()
    except ValueError as e:
        return _error(str(e), 403)
    backup_path = (BACKUP_DIR / Path(backup_name).name).resolve()
    if BACKUP_DIR.resolve() not in backup_path.parents:
        return _error("Invalid backup path", 403)
    if not backup_path.exists() or not backup_path.is_file():
        return _error("Backup not found", 404)
    pre_rollback_backup = backup_file(safe_path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, safe_path)
    return jsonify({
        "status": "rolled_back",
        "file": str(safe_path),
        "backup": str(backup_path),
        "pre_rollback_backup": pre_rollback_backup,
    })


def register_routes(app, state, require_auth):
    _auth_blueprint(config_bp, require_auth)
    app.register_blueprint(config_bp)
