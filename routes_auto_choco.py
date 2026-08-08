# Auto-added feature: chocolatey/choco (11446 stars)
# Description: Chocolatey - the package manager for Windows — search, install, upgrade, uninstall, list, and manage software packages via CLI
# Source: https://github.com/chocolatey/choco

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "chocolatey/choco",
    "stars": 11446,
    "desc": "Chocolatey package manager for Windows — search, install, upgrade, uninstall, list, pin, and manage software packages from the command line and automate software management",
    "url": "https://github.com/chocolatey/choco",
    "added": "2026-07-11",
    "command": "choco <install|search|upgrade|uninstall|list|info|pin|outdated>",
}


def _find_choco():
    """Locate choco.exe — typically in ProgramData or on PATH."""
    exe = shutil.which("choco") or shutil.which("choco.exe")
    if exe:
        return exe
    # Common fallback paths
    for p in [
        r"C:\ProgramData\chocolatey\choco.exe",
        r"C:\ProgramData\chocolatey\bin\choco.exe",
        os.path.expandvars(r"%ProgramData%\chocolatey\choco.exe"),
        os.path.expandvars(r"%ProgramData%\chocolatey\bin\choco.exe"),
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_choco_available():
    """Check choco responds by running a minimal command."""
    exe = _find_choco()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _clean_package_name(value):
    """Validate and sanitize a Chocolatey package name/ID."""
    name = str(value or "").strip()
    if not name:
        raise ValueError("package name must not be empty")
    if len(name) > 256:
        raise ValueError("package name too long (max 256 chars)")
    if "\x00" in name:
        raise ValueError("package name cannot contain null bytes")
    # Chocolatey package names are alphanumeric with dots and dashes.
    # Reject anything outside [a-zA-Z0-9._-] and leading dashes.
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', name):
        raise ValueError(f"package name contains invalid characters: {name!r}")
    return name


def register_routes(app, state, require_auth):
    @app.route("/auto/choco/info", methods=["GET"])
    @require_auth
    def route_auto_choco_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/choco/ping", methods=["GET"])
    @require_auth
    def route_auto_choco_ping():
        exe = _find_choco()
        available = _is_choco_available() if exe else False
        version = None
        if available:
            try:
                result = subprocess.run(
                    [exe, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                version = result.stdout.strip() if result.returncode == 0 else None
            except (subprocess.TimeoutExpired, OSError):
                pass
        return jsonify({
            "status": "ok",
            "feature": "chocolatey/choco",
            "available": available,
            "version": version,
            "command": exe or "choco",
        })

    @app.route("/auto/choco/search", methods=["POST"])
    @require_auth
    def route_auto_choco_search():
        """Search for packages on Chocolatey community feed."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        query = body.get("query", "")
        try:
            query = _clean_package_name(query) if query else query
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        if not query:
            return jsonify({"ok": False, "error": _missing_field("query")}), 400

        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        try:
            result = subprocess.run(
                [exe, "search", query, "--limit", "30"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "search failed",
                }), 502
            return jsonify({
                "ok": True,
                "query": query,
                "raw_output": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco search timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/list", methods=["GET"])
    @require_auth
    def route_auto_choco_list():
        """List locally installed Chocolatey packages."""
        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        try:
            result = subprocess.run(
                [exe, "list", "--local-only"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "list failed",
                }), 502

            packages = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line or "packages installed" in line or "chocolatey" in line.lower() and "v" in line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    packages.append({
                        "name": parts[0],
                        "version": parts[1].lstrip("v"),
                    })
                elif parts:
                    packages.append({"name": parts[0], "version": ""})
            return jsonify({
                "ok": True,
                "count": len(packages),
                "packages": packages,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco list timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/install", methods=["POST"])
    @require_auth
    def route_auto_choco_install():
        """Install a package via Chocolatey."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_name = body.get("package_name", "")
        try:
            package_name = _clean_package_name(package_name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        version = body.get("version", "")
        force = body.get("force") is True
        params = body.get("params", "")
        install_args = body.get("install_args", "")

        cmd = [exe, "install", package_name, "-y"]
        if version:
            cmd.extend(["--version", version])
        if force:
            cmd.append("--force")
        if params:
            cmd.extend(["--params", params])
        if install_args:
            cmd.extend(["--install-arguments", install_args])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_name": package_name,
                "version": version or "latest",
                "exit_code": result.returncode,
                "stdout": result.stdout.strip()[-2000:],
                "stderr": result.stderr.strip()[-1000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco install timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/upgrade", methods=["POST"])
    @require_auth
    def route_auto_choco_upgrade():
        """Upgrade a package (or all packages) via Chocolatey."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_name = body.get("package_name", "")
        if package_name:
            try:
                package_name = _clean_package_name(package_name)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
        elif body.get("all") is not True:
            return jsonify({"ok": False, "error": "package_name required, or set all=true to upgrade all"}), 400

        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        cmd = [exe, "upgrade", package_name if package_name else "all", "-y"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_name": package_name or "all",
                "exit_code": result.returncode,
                "stdout": result.stdout.strip()[-2000:],
                "stderr": result.stderr.strip()[-1000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco upgrade timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/uninstall", methods=["POST"])
    @require_auth
    def route_auto_choco_uninstall():
        """Uninstall a package via Chocolatey."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_name = body.get("package_name", "")
        try:
            package_name = _clean_package_name(package_name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        try:
            result = subprocess.run(
                [exe, "uninstall", package_name, "-y"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return jsonify({
                "ok": result.returncode == 0,
                "package_name": package_name,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip()[-2000:],
                "stderr": result.stderr.strip()[-1000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco uninstall timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/outdated", methods=["GET"])
    @require_auth
    def route_auto_choco_outdated():
        """List outdated packages that can be upgraded."""
        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        try:
            result = subprocess.run(
                [exe, "outdated"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or "outdated check failed",
                }), 502

            packages = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line or "Outdated Packages" in line or "---" in line:
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    packages.append({
                        "name": parts[0].strip(),
                        "current_version": parts[1].strip(),
                        "available_version": parts[2].strip(),
                    })
            return jsonify({
                "ok": True,
                "count": len(packages),
                "outdated_packages": packages,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco outdated timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/choco/info_pkg", methods=["POST"])
    @require_auth
    def route_auto_choco_info_pkg():
        """Get detailed info about a package from the Chocolatey community feed."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        package_name = body.get("package_name", "")
        try:
            package_name = _clean_package_name(package_name)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        exe = _find_choco()
        if not exe:
            return jsonify({"ok": False, "error": "choco not found"}), 503

        try:
            result = subprocess.run(
                [exe, "info", package_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "error": result.stderr.strip() or f"package '{package_name}' not found",
                }), 404
            return jsonify({
                "ok": True,
                "package_name": package_name,
                "details": result.stdout.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "choco info timed out"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
