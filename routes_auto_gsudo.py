# Auto-added feature: gerardog/gsudo (6019 stars)
# Sudo for Windows — run elevated commands from CoAgent
# Source: https://github.com/gerardog/gsudo
# Install: winget install gsudo  OR  scoop install gsudo
# CLI: gsudo [command]  — runs a command elevated via UAC

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "gerardog/gsudo",
    "stars": 6019,
    "desc": "Sudo for Windows \u2014 run elevated commands with UAC. Enables CoAgent to execute admin-privileged operations like service control, registry writes, and system configuration changes.",
    "url": "https://github.com/gerardog/gsudo",
    "added": "2026-08-05",
    "command": "gsudo [command]",
    "install": {
        "winget": "winget install gerardog.gsudo",
        "scoop": "scoop install gsudo",
        "choco": "choco install gsudo",
    },
    "modes": [
        "gsudo [cmd]         - Run cmd elevated (UAC prompt)",
        "gsudo -k             - Terminate all cached gsudo sessions",
        "gsudo config CacheMode Disabled - Disable credential cache",
    ],
}


def _find_gsudo():
    """Locate gsudo executable on this system."""
    exe = shutil.which("gsudo")
    if exe:
        return exe
    for p in [
        r"C:\Program Files\gsudo\gsudo.exe",
        r"C:\Program Files (x86)\gsudo\gsudo.exe",
        r"C:\Tools\gsudo\gsudo.exe",
    ]:
        import os
        if os.path.isfile(p):
            return p
    return None


def register_routes(app, state, require_auth):
    @app.route("/auto/gsudo/info", methods=["GET"])
    @require_auth
    def route_auto_gsudo_info():
        info = dict(FEATURE_INFO)
        exe = _find_gsudo()
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
                info["version"] = r.stdout.strip() or r.stderr.strip()
            except Exception:
                info["version"] = "unknown"
        return jsonify(info)

    @app.route("/auto/gsudo/ping", methods=["GET"])
    @require_auth
    def route_auto_gsudo_ping():
        exe = _find_gsudo()
        return jsonify({
            "status": "ok" if exe else "not_installed",
            "feature": "gerardog/gsudo",
            "path": exe,
        })

    @app.route("/auto/gsudo/run", methods=["POST"])
    @require_auth
    def route_auto_gsudo_run():
        """Run a command with elevated privileges via gsudo.
        Body: {"command": "whoami", "timeout": 30, "accept_elevation": true}
        Returns: {"stdout": "...", "stderr": "...", "exit_code": 0}
        """
        body = _json_body()
        if not body:
            return jsonify({"error": "JSON body required"}), 400
        command = body.get("command", "").strip()
        if not command:
            return _missing_field("command")
        try:
            timeout = int(body.get("timeout", 30))
        except (TypeError, ValueError):
            return jsonify({"error": "timeout must be an integer", "command": command}), 400
        if timeout <= 0:
            return jsonify({"error": "timeout must be positive", "command": command}), 400
        timeout = min(timeout, 120)
        accept = body.get("accept_elevation", False)

        exe = _find_gsudo()
        if not exe:
            return jsonify({
                "error": "gsudo not found",
                "install_hint": "winget install gerardog.gsudo",
            }), 503

        if not accept:
            return jsonify({
                "warning": "Elevation not accepted",
                "hint": "Set accept_elevation=true to confirm you want to run this elevated",
                "command": command,
            }), 403

        try:
            # Build args: gsudo accepts command as remaining args.
            # posix=False on Windows keeps backslashes intact (POSIX rules
            # would mangle paths like C:\Users\x into C:Usersx).
            import shlex
            args = [exe] + shlex.split(command, posix=(os.name != "nt"))
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return jsonify({
                "stdout": r.stdout,
                "stderr": r.stderr,
                "exit_code": r.returncode,
                "command": command,
            })
        except subprocess.TimeoutExpired:
            return jsonify({
                "error": f"Command timed out after {timeout}s",
                "command": command,
            }), 504
        except FileNotFoundError:
            return jsonify({
                "error": "gsudo executable disappeared",
                "path": exe,
            }), 500
        except Exception as e:
            _log(f"gsudo run failed: {e}")
            return jsonify({
                "error": str(e),
                "command": command,
            }), 500

    @app.route("/auto/gsudo/status", methods=["GET"])
    @require_auth
    def route_auto_gsudo_status():
        """Check if gsudo has an active elevated session (cached credentials)."""
        exe = _find_gsudo()
        if not exe:
            return jsonify({"error": "gsudo not found"}), 503
        try:
            # gsudo -k status check — if credentials are cached, whoami runs silently
            r = subprocess.run(
                [exe, "whoami"],
                capture_output=True, text=True, timeout=5,
            )
            return jsonify({
                "elevated": r.returncode == 0,
                "user": r.stdout.strip() if r.returncode == 0 else None,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
