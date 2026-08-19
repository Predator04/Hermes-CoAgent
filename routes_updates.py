"""Self-update and restart routes for Hermes CoAgent.

v3 — atomic staging, release-tarball integrity, health-checked restart, filesystem lock.
"""

import errno
import hashlib
import json
import logging
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

from shared import COAGENT_DIR, VERSION, _self_port


LOG = logging.getLogger("coagent.updates")

updates_bp = Blueprint("updates", __name__)

GITHUB_API_LATEST = "https://api.github.com/repos/Predator04/Hermes-CoAgent/releases/latest"
PRESERVE_FILES = {".token", "telegram_config.json", "config.json"}
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git"}
RESTART_FLAG = COAGENT_DIR / ".restart_requested"
LOCK_PATH = COAGENT_DIR / ".update.lock"

_RESTART_LOCK = threading.Lock()
_LOCK_FD: int | None = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _close_lock_fd() -> None:
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            os.close(_LOCK_FD)
        except Exception:
            pass
        _LOCK_FD = None


def _acquire_fs_lock() -> bool:
    """Exclusive filesystem lock — survives process restarts."""
    global _LOCK_FD
    try:
        _LOCK_FD = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(_LOCK_FD, msvcrt.LK_NBLCK, 1)
            else:
                os.lockf(_LOCK_FD, os.F_TLOCK, 0)
        except OSError as exc:
            _close_lock_fd()
            if os.name == "nt":
                return False
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        os.write(_LOCK_FD, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
        return True
    except Exception:
        _close_lock_fd()
        return False


def _release_fs_lock() -> None:
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(_LOCK_FD, msvcrt.LK_UNLCK, 1)
            else:
                os.lockf(_LOCK_FD, os.F_ULOCK, 0)
        except Exception:
            pass
        try:
            os.close(_LOCK_FD)
        except Exception:
            pass
        _LOCK_FD = None
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _request_json(url, token=""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Hermes-CoAgent-Updater/3.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            body = exc.read().decode("utf-8", errors="replace").lower()
            if "rate limit" in body:
                raise RuntimeError("GitHub API rate limit exceeded") from exc
        if exc.code == 404:
            return {"_not_found": True}
        raise


def _download(url, destination, max_size_mb=100):
    req = urllib.request.Request(url, headers={"User-Agent": "Hermes-CoAgent-Updater/3.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_size_mb * 1024 * 1024:
            raise RuntimeError(f"Tarball too large: {int(content_length)} bytes")
        buf = bytearray(8192)
        view = memoryview(buf)
        total = 0
        with open(destination, "wb") as f:
            while True:
                n = resp.readinto(buf)  # type: ignore[attr-defined]
                if n == 0:
                    break
                total += n
                if total > max_size_mb * 1024 * 1024:
                    raise RuntimeError("Download exceeded size limit")
                f.write(view[:n])


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("refs/tags/"):
        text = text.rsplit("/", 1)[-1]
    return text.lstrip("vV")


def _version_tuple(value: str) -> tuple:
    try:
        from packaging.version import Version
        return tuple(Version(_normalize_version(value)).release)
    except ImportError:
        # Fallback: simple numeric split
        parts = []
        for part in re.split(r"[^0-9]+", _normalize_version(value)):
            if part:
                parts.append(int(part))
        return tuple(parts or [0])


def _latest_release():
    try:
        release = _request_json(GITHUB_API_LATEST)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return _no_release_result()
        raise
    if release.get("_not_found"):
        return _no_release_result()

    tag = release.get("tag_name") or ""
    latest_version = _normalize_version(tag)
    update_available = _version_tuple(latest_version) > _version_tuple(VERSION)

    # Find tarball asset URL (prefer .tar.gz asset, fall back to tarball_url)
    tarball_url = release.get("tarball_url", "")
    sha256 = ""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith((".tar.gz", ".tgz")):
            tarball_url = asset.get("browser_download_url", tarball_url)
        if name.endswith(".sha256"):
            try:
                req = urllib.request.Request(
                    asset.get("browser_download_url", ""),
                    headers={"User-Agent": "Hermes-CoAgent-Updater/3.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as sha_resp:
                    sha_text = sha_resp.read().decode("utf-8").strip()
                    # Format: "<hex>  <filename>" or just "<hex>"
                    sha256 = sha_text.split()[0] if sha_text else ""
            except Exception:
                pass

    return {
        "current": VERSION,
        "latest": latest_version,
        "update_available": update_available,
        "release_url": release.get("html_url"),
        "published_at": release.get("published_at"),
        "tag": tag,
        "tarball_url": tarball_url,
        "sha256": sha256,
        "raw": release,
    }


def _no_release_result():
    return {
        "current": VERSION,
        "latest": VERSION,
        "update_available": False,
        "release_url": "https://github.com/Predator04/Hermes-CoAgent/releases",
        "published_at": None,
        "tag": "",
        "tarball_url": "",
        "sha256": "",
    }


# ── tarball extraction ───────────────────────────────────────────────────────

def _safe_tar_members(tar, destination):
    dest = str(Path(destination).resolve())
    safe = []
    for member in tar.getmembers():
        # Reject symlinks, hardlinks, devices
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            LOG.warning("update: skipping non-regular entry %s", member.name)
            continue
        # Reject absolute / relative traversal
        name = os.path.normpath(member.name)
        if os.path.isabs(name) or name.startswith(".."):
            LOG.warning("update: skipping traversal attempt %s", member.name)
            continue
        target = os.path.normpath(os.path.join(dest, name))
        if not target.startswith(dest + os.sep) and target != dest:
            LOG.warning("update: skipping out-of-tree %s → %s", member.name, target)
            continue
        # Secure modes: 755 for exec/dirs, 644 for files
        is_exec = (member.mode & 0o111) != 0
        member.mode = 0o755 if (member.isdir() or is_exec) else 0o644
        member.name = name  # normalised
        safe.append(member)
    return safe


def _extract_tarball(tarball_path, extract_dir):
    with tarfile.open(tarball_path, "r:*") as tar:
        members = _safe_tar_members(tar, extract_dir)
        tar.extractall(extract_dir, members=members)
    roots = [item for item in Path(extract_dir).iterdir() if item.is_dir()]
    return roots[0] if len(roots) == 1 else Path(extract_dir)


# ── atomic swap ──────────────────────────────────────────────────────────────

def _atomic_update(source_dir, dest_dir, preserve):
    """Stage to sibling dir, then atomic rename."""
    dest = Path(dest_dir).resolve()
    staging = dest.with_name(dest.name + ".staging")
    backup = dest.with_name(dest.name + ".bak")

    # Clean leftover staging/backup
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    # Copy new files to staging
    staging.mkdir(parents=True, exist_ok=True)
    for item in Path(source_dir).rglob("*"):
        rel = item.relative_to(source_dir)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        # Only skip top-level preserve files
        if len(rel.parts) == 1 and rel.parts[0] in preserve:
            continue
        target = staging / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    # Copy preserved files from dest into staging BEFORE the swap
    # (these files are intentionally excluded from the tarball and must survive)
    if dest.exists():
        for p in preserve:
            src = dest / p
            if src.is_file():
                dst = staging / p
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            elif src.is_dir():
                dst = staging / p
                if not dst.exists():
                    shutil.copytree(str(src), str(dst))

    # Atomic swap with rollback
    if dest.exists():
        dest.rename(backup)
    try:
        staging.rename(dest)
    except Exception:
        # Rollback: restore backup to dest
        if backup.exists():
            backup.rename(dest)
        raise

    # Clean up
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    return True


# ── restart ──────────────────────────────────────────────────────────────────

def _pythonw_executable():
    current = Path(sys.executable)
    if current.name.lower() == "python.exe":
        candidate = current.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    found = shutil.which("pythonw.exe") or shutil.which("pythonw")
    if not found:
        raise RuntimeError("pythonw.exe not found — cannot restart invisibly")
    return found


def _launch_replacement():
    env = dict(os.environ)  # Start with full environment to ensure pythonw starts correctly
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    args = [_pythonw_executable(), str(COAGENT_DIR / "hermes_coagent.py")]
    for _arg in sys.argv[1:]:
        if _arg in ("--secure", "--allow-external") or _arg.startswith("--token="):
            args.append(_arg)
    subprocess.Popen(
        args,
        cwd=str(COAGENT_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
        close_fds=True,
    )


def _health_check(url, timeout=30, interval=1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _restart_after_delay(delay=1.0):
    def _worker():
        time.sleep(delay)
        try:
            _launch_replacement()
            # Wait for new process to come alive
            alive = _health_check(f"http://127.0.0.1:{_self_port()}/ping", timeout=15)
            if alive:
                LOG.info("update: replacement healthy, exiting")
                os._exit(0)
            else:
                LOG.error("update: replacement did not become healthy; staying alive")
                _release_fs_lock()
        except Exception as exc:
            LOG.error("update: replacement launch failed: %s", exc)
            _release_fs_lock()

    threading.Thread(target=_worker, name="coagent-restart", daemon=True).start()


def _touch_restart_flag(reason):
    RESTART_FLAG.write_text(
        json.dumps({"reason": reason, "timestamp": time.time(), "version": VERSION}, indent=2),
        encoding="utf-8",
    )


# ── routes ───────────────────────────────────────────────────────────────────

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
    # Acquire filesystem lock (in-process lock is insufficient across restarts)
    if not _acquire_fs_lock():
        return jsonify({"error": "update already in progress"}), 409

    # Hold the lock until exit — DO NOT release in finally
    try:
        latest = _latest_release()
    except Exception as exc:
        _release_fs_lock()
        return jsonify({"error": "update check failed", "detail": str(exc)}), 502

    if not latest.get("update_available"):
        _release_fs_lock()
        return jsonify({
            "status": "current",
            "current": VERSION,
            "latest": latest.get("latest") or VERSION,
            "update_available": False,
        }), 200

    tarball_url = latest.get("tarball_url", "")
    if not tarball_url:
        _release_fs_lock()
        return jsonify({"error": "no tarball URL in release"}), 502

    # Download + verify + atomically swap
    try:
        with tempfile.TemporaryDirectory(prefix="coagent-update-") as tmp:
            tmp_path = Path(tmp)
            tarball = tmp_path / "coagent.tar.gz"
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()

            _download(tarball_url, tarball)

            # Verify checksum if available
            expected_sha = latest.get("sha256", "")
            if expected_sha:
                actual = _sha256_file(str(tarball))
                if actual != expected_sha:
                    _release_fs_lock()
                    return jsonify({"error": "checksum mismatch", "expected": expected_sha, "got": actual}), 500

            update_root = _extract_tarball(tarball, extract_dir)

            # Atomic swap into place
            _atomic_update(update_root, COAGENT_DIR, PRESERVE_FILES)

    except Exception as exc:
        _release_fs_lock()
        LOG.exception("update: apply failed")
        return jsonify({"error": "update apply failed", "detail": str(exc)}), 500

    _touch_restart_flag("update_apply")
    _restart_after_delay(1.0)

    return jsonify({
        "status": "ok",
        "version": latest.get("latest") or VERSION,
        "restarting": True,
        "preserved": sorted(PRESERVE_FILES),
    })
    # Lock intentionally NOT released — os._exit() in restart thread cleans it up


@updates_bp.route("/update/restart", methods=["POST"])
def route_update_restart():
    if not _acquire_fs_lock():
        return jsonify({"error": "restart already in progress"}), 409
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
