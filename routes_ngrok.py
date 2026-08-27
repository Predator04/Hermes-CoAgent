"""Ngrok auto-install and configure routes.

Endpoint:
  POST /tunnel/ensure  - ensure ngrok is present on this machine. If it is
                         missing, download the official Windows amd64 build,
                         extract it to %LOCALAPPDATA%\\Ngrok\\ngrok.exe, and
                         (optionally) configure an auth token so it is ready
                         for the deploy + tray "Start Tunnel" flows.

Also exposes an importable ``ensure_ngrok()`` helper used by
``routes_deploy`` and ``routes_media`` so the tunnel endpoints can install
ngrok on demand on a fresh Windows machine.

All PowerShell/subprocess strings kept pure ASCII per project rules.
"""

import io
import os
import re
import shutil
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path

from flask import jsonify

from shared import _json_body, _log


NGROK_DOWNLOAD_URL = (
    "https://bin.equinox.io/c/bNyj1mQVY4c/"
    "ngrok-v3-stable-windows-amd64.zip"
)

_ENSURE_LOCK = threading.Lock()


def _install_dir() -> Path:
    """Return the writable per-user install dir for ngrok.exe."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    return Path(base) / "Ngrok"


def _find_ngrok() -> str | None:
    """Locate ngrok.exe on PATH or in our per-user install dir."""
    found = shutil.which("ngrok") or shutil.which("ngrok.exe")
    if found:
        return found
    candidate = _install_dir() / "ngrok.exe"
    if candidate.exists():
        return str(candidate)
    return None


_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — the ngrok zip is ~15 MB; cap to avoid OOM/zip-bomb


def _download_zip(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CoAgent-Ngrok-Installer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        chunks = []
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    f"download exceeds {_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB safety cap"
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _extract_ngrok(zip_bytes: bytes, dest_dir: Path) -> Path:
    """Extract ngrok.exe from the downloaded zip to dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        exe_name = None
        for name in zf.namelist():
            # Only accept a member whose basename is exactly ngrok.exe. We
            # write to a fixed target path under dest_dir, so a traversal-style
            # entry name can never influence where the payload lands.
            base = name.replace("\\", "/").rstrip("/").split("/")[-1]
            if base.lower() == "ngrok.exe":
                exe_name = name
                break
        if not exe_name:
            raise RuntimeError("ngrok.exe not found inside downloaded zip")
        target = dest_dir / "ngrok.exe"
        tmp = dest_dir / "ngrok.exe.tmp"
        try:
            with zf.open(exe_name) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, target)
        finally:
            # Never leave a partial ngrok.exe.tmp behind (e.g. target busy).
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    return target


def _configure_authtoken(ngrok_path: str, token: str, timeout: int = 20) -> tuple[bool, str]:
    """Run 'ngrok config add-authtoken <token>'. Returns (ok, stderr)."""
    try:
        r = subprocess.run(
            [ngrok_path, "config", "add-authtoken", token],
            capture_output=True, text=True, timeout=timeout,
        )
        return (r.returncode == 0, (r.stderr or "").strip())
    except Exception as exc:  # noqa: BLE001
        return (False, f"{type(exc).__name__}: {exc}")


def _ngrok_version(ngrok_path: str, timeout: int = 10) -> str | None:
    try:
        r = subprocess.run(
            [ngrok_path, "version"],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0:
            lines = (r.stdout or "").strip().splitlines()
            return lines[0] if lines else None
    except Exception:
        return None
    return None


def ensure_ngrok(auth_token: str | None = None) -> dict:
    """Ensure ngrok is installed. Download + install if missing.

    Returns a dict describing the outcome:
      {ok, path, installed, downloaded, configured, version, error?}
    """
    with _ENSURE_LOCK:
        existing = _find_ngrok()
        downloaded = False
        error = None
        if existing:
            path = existing
        else:
            if os.name != "nt":
                return {
                    "ok": False,
                    "path": None,
                    "installed": False,
                    "downloaded": False,
                    "configured": False,
                    "version": None,
                    "error": "ngrok auto-install is Windows-only",
                }
            try:
                _log("ngrok not found — downloading official Windows build")
                zip_bytes = _download_zip(NGROK_DOWNLOAD_URL)
                target = _extract_ngrok(zip_bytes, _install_dir())
                path = str(target)
                downloaded = True
                _log(f"ngrok installed at {path}")
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "path": None,
                    "installed": False,
                    "downloaded": False,
                    "configured": False,
                    "version": None,
                    "error": f"download/install failed: {type(exc).__name__}: {exc}",
                }

        configured = False
        if auth_token:
            ok, err = _configure_authtoken(path, auth_token.strip())
            configured = ok
            if not ok:
                error = err or "add-authtoken failed"

        version = _ngrok_version(path)
        return {
            "ok": error is None,
            "path": path,
            "installed": True,
            "downloaded": downloaded,
            "configured": configured,
            "version": version,
            "error": error,
        }


_AUTHTOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,256}$")


def register_routes(app, state, require_auth):
    @app.route("/tunnel/ensure", methods=["POST"])
    @require_auth
    def route_tunnel_ensure():
        body = _json_body()
        if not isinstance(body, dict):
            body = {}
        auth_token = body.get("authtoken") or body.get("auth_token") or None
        if auth_token is not None:
            if not isinstance(auth_token, str):
                return jsonify({"error": "authtoken must be a string"}), 400
            auth_token = auth_token.strip()
            if not _AUTHTOKEN_RE.match(auth_token):
                return jsonify({
                    "error": "authtoken must be 8-256 chars of letters, digits, '_' or '-'"
                }), 400

        result = ensure_ngrok(auth_token=auth_token)
        status = 200 if result.get("ok") else 500
        return jsonify(result), status
