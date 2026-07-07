# Auto-added feature: microsoft/winget-cli (26130 stars)
# Description: WinGet is the Windows Package Manager — search, install, upgrade, list, and manage software packages from the command line
# Source: https://github.com/microsoft/winget-cli

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/winget-cli",
    "stars": 26130,
    "desc": "Windows Package Manager — search, install, upgrade, list, uninstall, export, and manage software packages via winget CLI",
    "url": "https://github.com/microsoft/winget-cli",
    "added": "2026-07-07",
    "command": "winget <install|search|list|upgrade|uninstall|export|show>",
}


def _find_winget():
    """Locate winget.exe — typically in WindowsApps or system32."""
    exe = shutil.which("winget") or shutil.which("winget.exe")
    if exe:
        return exe
    # Common fallback paths
    for p in [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"),
        r"C:\Users\Admin\AppData\Local\Microsoft\WindowsApps\winget.exe",
        r"C:\Windows\system32\winget.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_winget_available():
    """Check winget responds by running a minimal command."""
    exe = _find_winget()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_package_id(value):
    """Validate and sanitize a winget package identifier."""
    pid = str(value or "").strip()
    if not pid:
        raise ValueError("package identifier must not be empty")
    if len(pid) > 256:
        raise ValueError("package identifier too long (max 256 chars)")
    if "\x00" in pid:
        raise ValueError("package identifier cannot contain null bytes")
    forbidden = set('<>"|?*')
    if any(c in pid for c in forbidden):
        raise ValueError(f"package identifier contains forbidden characters: {forbidden & set(pid)}")
    return pid


def _clean_query(value):
    """Validate a search query string."""
    q = str(value or "").strip()
    if not q:
        raise ValueError("query must not be empty")
    if len(q) > 200:
        raise ValueError("query too long (max 200 chars)")
    if "\x00" in q:
        raise ValueError("query cannot contain null bytes")
    return q


def register_routes(app, state, require_auth):
    @app.route("/auto/winget_cli/info", methods=["GET"])
    @require_auth
    def route_auto_winget_cli_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/winget_cli/ping", methods=["GET"])
    @require_auth
    def route_auto_winget_cli_ping():
        exe = _find_winget()
        available = _is_winget_available() if exe else False
        version = None
        if available:
            try:
                result = subprocess.run(
                    [exe, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                version = result.stdout.strip() if result.returncode == 0 else None
            except (subprocess.TimeoutExpired, OSError):
                pass
        return jsonify({
            "status": "ok",
            "feature": "microsoft/winget-cli",
            "available": available,
            "version": version,
            "command": exe or "winget",
        })

    @app.route("/auto/winget_cli/search", methods=["POST"])
    @require_auth
    def route_auto_winget_cli_search():
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        query = body.get("query", "")
        try:
            query = _clean_query(query)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        try:
            result = subprocess.run(
                [exe, "search", query, "--accept-source-agreements"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "search failed",
                }), 502
            lines = result.stdout.strip().split("\n")
            # Parse winget table output — skip header/separator lines
            packages = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Name") or line.startswith("---"):
                    continue
                parts = [p.strip() for p in line.split() if p.strip()]
                if parts:
                    packages.append({
                        "name": parts[0] if len(parts) > 0 else "",
                        "id": parts[1] if len(parts) > 1 else parts[0],
                        "version": parts[2] if len(parts) > 2 else "",
                        "source": parts[3] if len(parts) > 3 else "winget",
                    })
            return jsonify({
                "ok": True,
                "query": query,
                "count": len(packages),
                "packages": packages,
                "raw_output": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget search timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/winget_cli/list", methods=["GET"])
    @require_auth
    def route_auto_winget_cli_list():
        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        try:
            result = subprocess.run(
                [exe, "list", "--accept-source-agreements"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "list failed",
                }), 502
            lines = result.stdout.strip().split("\n")
            packages = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Name") or line.startswith("---"):
                    continue
                parts = [p.strip() for p in line.split() if p.strip()]
                if parts:
                    packages.append({
                        "name": parts[0] if len(parts) > 0 else "",
                        "id": parts[1] if len(parts) > 1 else parts[0],
                        "version": parts[2] if len(parts) > 2 else "",
                        "available": parts[3] if len(parts) > 3 else "",
                    })
            return jsonify({
                "ok": True,
                "count": len(packages),
                "packages": packages,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget list timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/winget_cli/install", methods=["POST"])
    @require_auth
    def route_auto_winget_cli_install():
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_id = body.get("package_id", "")
        try:
            package_id = _clean_package_id(package_id)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        silent = body.get("silent", True)
        try:
            cmd = [exe, "install", "--exact", "--id", package_id, "--accept-source-agreements", "--accept-package-agreements"]
            if silent:
                cmd.append("--silent")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_id": package_id,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget install timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/winget_cli/upgrade", methods=["POST"])
    @require_auth
    def route_auto_winget_cli_upgrade():
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_id = body.get("package_id", "")
        try:
            package_id = _clean_package_id(package_id) if package_id else None
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        try:
            cmd = [exe, "upgrade", "--accept-source-agreements", "--accept-package-agreements"]
            if package_id:
                cmd.extend(["--id", package_id])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_id": package_id or "all",
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget upgrade timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/winget_cli/show", methods=["POST"])
    @require_auth
    def route_auto_winget_cli_show():
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_id = body.get("package_id", "")
        try:
            package_id = _clean_package_id(package_id)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        try:
            result = subprocess.run(
                [exe, "show", "--id", package_id, "--accept-source-agreements"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or f"package '{package_id}' not found",
                }), 404
            return jsonify({
                "ok": True,
                "package_id": package_id,
                "details": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget show timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/winget_cli/uninstall", methods=["POST"])
    @require_auth
    def route_auto_winget_cli_uninstall():
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_id = body.get("package_id", "")
        try:
            package_id = _clean_package_id(package_id)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_winget()
        if not exe:
            return jsonify({"ok": False, "error": "winget not found"}), 503

        try:
            result = subprocess.run(
                [exe, "uninstall", "--id", package_id, "--accept-source-agreements"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_id": package_id,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "winget uninstall timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
