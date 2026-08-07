"""Self-update and restart routes for Hermes CoAgent."""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from flask import Blueprint, jsonify

from shared import COAGENT_DIR, VERSION, _console


updates_bp = Blueprint("updates", __name__)

GITHUB_LATEST_URL = "https://api.github.com/repos/Predator04/Hermes-CoAgent/releases/latest"
GITHUB_TARBALL_URL = "https://api.github.com/repos/Predator04/Hermes-CoAgent/tarball/main"
PRESERVE_FILES = {".token", "telegram_config.json", "config.json"}
RESTART_FLAG = COAGENT_DIR / ".restart_requested"
_UPDATE_LOCK = threading.Lock()


def _request_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Hermes-CoAgent-Updater/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and "rate limit" in str(exc).lower():
            raise RuntimeError("GitHub API rate limit exceeded (403)") from exc
        raise


def _download(url, destination):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Hermes-CoAgent-Updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)


def _normalize_version(value):
    text = str(value or "").strip()
    if text.startswith("refs/tags/"):
        text = text.rsplit("/", 1)[-1]
    return text.lstrip("vV")


def _version_tuple(value):
    normalized = _normalize_version(value)
    parts = []
    for part in re.split(r"[^0-9]+", normalized):
        if part:
            parts.append(int(part))
    return tuple(parts or [0])


def _latest_release():
    try:
        release = _request_json(GITHUB_LATEST_URL)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "current": VERSION,
                "latest": VERSION,
                "update_available": False,
                "release_url": "https://github.com/Predator04/Hermes-CoAgent/releases",
                "published_at": None,
                "warning": "latest release not found",
                "raw": {},
            }
        raise
    latest = release.get("tag_name") or release.get("name") or ""
    return {
        "current": VERSION,
        "latest": _normalize_version(latest),
        "update_available": _version_tuple(latest) > _version_tuple(VERSION),
        "release_url": release.get("html_url"),
        "published_at": release.get("published_at"),
        "raw": release,
    }


def _safe_tar_members(tar, destination):
    destination = Path(destination).resolve()
    safe = []
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            continue
        target = (destination / member.name).resolve()
        try:
            if os.path.commonpath([str(destination), str(target)]) != str(destination):
                continue
        except ValueError:
            continue
        # Strip dangerous mode bits (setuid, setgid, world-writable)
        if member.mode:
            member.mode = member.mode & 0o755
        safe.append(member)
    return safe


def _extract_tarball(tarball_path, extract_dir):
    with tarfile.open(tarball_path, "r:*") as tar:
        members = _safe_tar_members(tar, extract_dir)
        tar.extractall(extract_dir, members=members)
    roots = [item for item in Path(extract_dir).iterdir() if item.is_dir()]
    if len(roots) == 1:
        return roots[0]
    return Path(extract_dir)


def _should_skip(path):
    name = path.name
    if name in PRESERVE_FILES:
        return True
    if name in {"__pycache__", ".pytest_cache"}:
        return True
    return False


def _copy_update_tree(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    copied = []
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        if any(part in PRESERVE_FILES for part in rel.parts):
            continue
        if any(part in {"__pycache__", ".pytest_cache"} for part in rel.parts):
            continue
        target = destination / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if _should_skip(item):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append(str(rel))
    return copied


def _pythonw_executable():
    current = Path(sys.executable)
    if current.name.lower() == "python.exe":
        candidate = current.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    found = shutil.which("pythonw.exe") or shutil.which("pythonw")
    return found or sys.executable


def _launch_replacement():
    args = [_pythonw_executable(), str(COAGENT_DIR / "hermes_coagent.py"), "--secure"]
    kwargs = {
        "cwd": str(COAGENT_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(args, **kwargs)


def _restart_after_delay(delay=1.0):
    def _worker():
        time.sleep(delay)
        try:
            _launch_replacement()
        finally:
            os._exit(0)

    threading.Thread(target=_worker, name="coagent-restart", daemon=True).start()


def _touch_restart_flag(reason):
    RESTART_FLAG.write_text(
        json.dumps({"reason": reason, "timestamp": time.time(), "version": VERSION}, indent=2),
        encoding="utf-8",
    )


@updates_bp.route("/update/check", methods=["GET"])
def route_update_check():
    try:
        latest = _latest_release()
        latest.pop("raw", None)
        return jsonify(latest)
    except urllib.error.HTTPError as exc:
        return jsonify({"error": "github request failed", "status": exc.code, "detail": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": "update check failed", "detail": str(exc)}), 502


@updates_bp.route("/update/apply", methods=["POST"])
def route_update_apply():
    if not _UPDATE_LOCK.acquire(blocking=False):
        return jsonify({"error": "update already in progress"}), 409
    try:
        try:
            latest = _latest_release()
        except Exception as exc:
            return jsonify({"error": "update check failed", "detail": str(exc)}), 502

        if not latest.get("update_available"):
            return jsonify(
                {
                    "status": "current",
                    "current": VERSION,
                    "latest": latest.get("latest") or VERSION,
                    "update_available": False,
                }
            ), 304

        try:
            with tempfile.TemporaryDirectory(prefix="coagent-update-") as tmp:
                tmp_path = Path(tmp)
                tarball_path = tmp_path / "coagent.tar.gz"
                extract_dir = tmp_path / "extract"
                extract_dir.mkdir()
                _download(GITHUB_TARBALL_URL, tarball_path)
                update_root = _extract_tarball(tarball_path, extract_dir)
                copied = _copy_update_tree(update_root, COAGENT_DIR)
        except Exception as exc:
            _console(f"[updates] apply failed: {exc}")
            return jsonify({"error": "update apply failed", "detail": str(exc)}), 500

        _touch_restart_flag("update_apply")
        _restart_after_delay(1.0)
        return jsonify(
            {
                "status": "ok",
                "version": latest.get("latest") or VERSION,
                "restarting": True,
                "files_copied": len(copied),
                "preserved": sorted(PRESERVE_FILES),
            }
        )
    finally:
        _UPDATE_LOCK.release()


@updates_bp.route("/update/restart", methods=["POST"])
def route_update_restart():
    _touch_restart_flag("manual_restart")
    _restart_after_delay(1.0)
    return jsonify({"status": "ok", "restarting": True})


def register_routes(app, state, require_auth):
    for endpoint, view_func in list(updates_bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        updates_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(updates_bp)
