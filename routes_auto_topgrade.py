# Auto-added feature: topgrade-rs/topgrade (4391 stars)
# "Upgrade all the things" — one command to upgrade every package manager & tool on the system
# Source: https://github.com/topgrade-rs/topgrade
# Install: winget install topgrade-rs.topgrade  OR  scoop install topgrade

import glob
import shutil
import subprocess
import os
from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "topgrade-rs/topgrade",
    "stars": 4391,
    "desc": "topgrade detects and upgrades every package manager and tool on your system in a single pass: winget, scoop, chocolatey, pip, npm, cargo, Windows Update, and more. One command keeps the entire machine current — perfect for autonomous self-maintenance. Supports --dry-run to preview, --only/--disable to scope steps, and --yes for unattended runs.",
    "url": "https://github.com/topgrade-rs/topgrade",
    "added": "2026-08-14",
    "command": "topgrade [--dry-run] [--yes] [--only <steps>] [--disable <steps>] [--cleanup]",
    "install": {
        "winget": "winget install topgrade-rs.topgrade",
        "scoop": "scoop install topgrade",
    },
    "endpoints": {
        "/auto/topgrade/info": "Feature metadata, install status, version",
        "/auto/topgrade/ping": "Health check",
        "/auto/topgrade/dry-run": "GET — preview what would be upgraded (no changes applied)",
        "/auto/topgrade/run": "POST — run system-wide upgrades (optional only/disable step filters, cleanup)",
        "/auto/topgrade/config": "GET — locate the topgrade config file",
    },
}


def _find_topgrade():
    """Locate topgrade on this system."""
    exe = shutil.which("topgrade")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\topgrade-rs.topgrade_*\topgrade.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\topgrade.exe"),
        os.path.expandvars(r"%USERPROFILE%\.cargo\bin\topgrade.exe"),
    ]
    for c in candidates:
        if "*" in c:
            matches = glob.glob(c)
            if matches:
                return matches[0]
        elif os.path.isfile(c):
            return c
    return None


def _get_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def _split_steps(value):
    """Normalize a step list that may be a list, comma string, or single string."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
    else:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
    return parts or None


def _find_config():
    candidates = [
        os.path.expandvars(r"%APPDATA%\topgrade.toml"),
        os.path.expandvars(r"%USERPROFILE%\.config\topgrade.toml"),
        os.path.expandvars(r"%USERPROFILE%\topgrade.toml"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def register_routes(app, state, require_auth):
    @app.route("/auto/topgrade/info", methods=["GET"])
    @require_auth
    def route_auto_topgrade_info():
        info = dict(FEATURE_INFO)
        exe = _find_topgrade()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _get_version(exe)
            info["config"] = _find_config()
        return jsonify(info)

    @app.route("/auto/topgrade/ping", methods=["GET"])
    @require_auth
    def route_auto_topgrade_ping():
        exe = _find_topgrade()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "topgrade-rs/topgrade",
            "path": exe,
        })

    @app.route("/auto/topgrade/dry-run", methods=["GET"])
    @require_auth
    def route_auto_topgrade_dry_run():
        """Preview what topgrade would upgrade, without applying anything."""
        exe = _find_topgrade()
        if not exe:
            return jsonify({
                "error": "topgrade not installed",
                "hint": "Install with: winget install topgrade-rs.topgrade",
            }), 503

        try:
            r = subprocess.run(
                [exe, "--dry-run"],
                capture_output=True, text=True, timeout=60,
            )
            output = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
            return jsonify({
                "success": r.returncode == 0,
                "exit_code": r.returncode,
                "output": output.strip(),
            })
        except subprocess.TimeoutExpired:
            _log("topgrade_dry_run: timed out")
            return jsonify({"error": "topgrade --dry-run timed out"}), 504
        except Exception as e:
            _log(f"topgrade_dry_run: Error: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/auto/topgrade/run", methods=["POST"])
    @require_auth
    def route_auto_topgrade_run():
        """Run system-wide upgrades. Unattended by default (--yes --no-retry).

        Body (all optional):
          only:     list or comma-string of steps to run (e.g. "winget,scoop")
          disable:  list or comma-string of steps to skip
          cleanup:  bool — run --cleanup to remove temp/old files after upgrading
          timeout:  int seconds (default 600, max 1800)
        """
        body = _json_body()
        only_steps = _split_steps(body.get("only"))
        disable_steps = _split_steps(body.get("disable"))
        cleanup = bool(body.get("cleanup", False))
        timeout = body.get("timeout", 600)

        try:
            timeout = int(timeout)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid timeout: {body.get('timeout')}"}), 400
        timeout = max(10, min(timeout, 1800))

        exe = _find_topgrade()
        if not exe:
            return jsonify({
                "error": "topgrade not installed",
                "hint": "Install with: winget install topgrade-rs.topgrade",
            }), 503

        cmd = [exe, "--yes", "--no-retry"]
        if only_steps:
            cmd.extend(["--only", ",".join(only_steps)])
        if disable_steps:
            cmd.extend(["--disable", ",".join(disable_steps)])
        if cleanup:
            cmd.append("--cleanup")

        _log(f"topgrade_run: {' '.join(cmd)}")

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            output = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
            return jsonify({
                "success": r.returncode == 0,
                "exit_code": r.returncode,
                "only": only_steps,
                "disable": disable_steps,
                "cleanup": cleanup,
                "output": output.strip(),
            })
        except subprocess.TimeoutExpired:
            _log(f"topgrade_run: timed out after {timeout}s")
            return jsonify({
                "error": f"topgrade timed out after {timeout}s (it may still be running upgrades)",
                "timeout": timeout,
                "success": False,
            }), 504
        except Exception as e:
            _log(f"topgrade_run: Error: {e}")
            return jsonify({"error": str(e), "success": False}), 500

    @app.route("/auto/topgrade/config", methods=["GET"])
    @require_auth
    def route_auto_topgrade_config():
        """Return the path to the topgrade config file, if it exists."""
        cfg = _find_config()
        if not cfg:
            return jsonify({
                "config": None,
                "message": "No topgrade.toml found. Create one to customize which steps run.",
            })
        try:
            with open(cfg, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            return jsonify({"config": cfg, "content": content})
        except Exception as e:
            _log(f"topgrade_config: Error reading {cfg}: {e}")
            return jsonify({"config": cfg, "error": str(e)}), 500
