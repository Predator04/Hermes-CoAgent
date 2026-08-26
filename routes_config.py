"""Config backup and rollback routes."""

import os
import re
import shutil
import time
from pathlib import Path

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import COAGENT_DIR, _sanitize_path, _wrap_registered_blueprint_routes


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


def _original_name_from_backup(backup_name):
    """Extract the original filename encoded in a backup filename.

    Backup names follow ``{original}.{YYYYMMDD-HHMMSS}[.{suffix}].bak``.
    Returns the ``original`` portion, or ``None`` if it can't be parsed.
    """
    m = re.search(r"\.\d{8}-\d{6}(?:\.\d+)?\.bak$", backup_name)
    return backup_name[: m.start()] if m else None


def _prune_backups_for(path: Path):
    # `*` in the glob also matches dots, so `config.yaml.*.bak` would also match
    # `config.yaml.new.<ts>.bak`. Filter by the decoded original name so we only
    # ever prune backups that actually belong to `path`.
    backups = sorted(
        (p for p in BACKUP_DIR.glob(f"{path.name}.*.bak")
         if _original_name_from_backup(p.name) == path.name),
        key=_stat_safe,
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


def _stat_safe(p):
    """Safely get mtime, returning 0 on any OSError."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0


def _list_backups():
    backups = []
    if not BACKUP_DIR.exists():
        return backups
    for item in sorted(BACKUP_DIR.glob("*.bak"), key=_stat_safe, reverse=True):
        try:
            stat = item.stat()
            # Strip .bak suffix, then parse original filename from backup naming convention
            name_no_bak = item.name[:-4] if item.name.endswith(".bak") else item.name
            # Backup format: {original}.{timestamp}.bak or {original}.{timestamp}.{suffix}.bak
            # Find the first dot that starts a YYYYMMDD-HHMMSS timestamp
            m = re.match(r"^(.+)\.\d{8}-\d{6}", name_no_bak)
            original = m.group(1) if m else name_no_bak
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
    backup_name = Path(backup_name).name
    backup_path = BACKUP_DIR / backup_name
    if backup_path.is_symlink():
        return _error("Invalid backup path", 403)
    if BACKUP_DIR.resolve() not in backup_path.resolve().parents:
        return _error("Invalid backup path", 403)
    if not backup_path.exists() or not backup_path.is_file():
        return _error("Backup not found", 404)
    if _original_name_from_backup(backup_name) != safe_path.name:
        return _error("Backup does not belong to the requested file", 403)
    if not safe_path.parent.exists():
        return _error("Target directory does not exist", 404)
    pre_rollback_backup = backup_file(safe_path)
    # Write to a temp file in the same directory, then atomically replace the
    # target so an interrupted rollback never leaves a truncated/corrupt file.
    tmp_path = safe_path.with_name(safe_path.name + ".rollback.tmp")
    try:
        shutil.copy2(backup_path, tmp_path)
        os.replace(tmp_path, safe_path)
    except OSError as e:
        return _error(f"Rollback failed: {e}", 500)
    return jsonify({
        "status": "rolled_back",
        "file": str(safe_path),
        "backup": str(backup_path),
        "pre_rollback_backup": pre_rollback_backup,
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(config_bp)
    _wrap_registered_blueprint_routes(app, config_bp.name, require_auth)
