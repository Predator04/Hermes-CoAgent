# Auto-added feature: microsoft/windows (built-in) — DISM
# Description: dism.exe — Deployment Imaging Service and Management Tool.
#   Manage Windows features/components, check image health, scan/restore system health,
#   list installed packages and features, enable/disable Windows features,
#   apply updates and drivers, manage CBS (Component Based Servicing) logs.
# Source: Built-in Windows tool at C:\Windows\system32\Dism.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Deployment Imaging Service and Management — query/restore component health, manage Windows features and packages, scan/restore system image, manage CBS logs, enable/disable optional features",
    "url": "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/dism-reference",
    "added": "2026-07-09",
    "command": "dism /online /<operation>",
}


def _find_dism():
    """Locate Dism.exe — typically in system32."""
    exe = shutil.which("dism") or shutil.which("Dism") or shutil.which("Dism.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\Dism.exe",
        r"C:\Windows\SysWOW64\Dism.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_dism_available():
    """Check dism responds by running a minimal command."""
    exe = _find_dism()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "/online", "/Get-CurrentEdition"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_dism(args, timeout=60):
    """Run dism.exe with given args, return parsed output or raise."""
    exe = _find_dism()
    if not exe:
        raise RuntimeError("Dism.exe not found on system")
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Dism operation timed out")
    except OSError as e:
        raise RuntimeError(f"Dism execution failed: {e}")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "Dism returned non-zero exit code")
    return result.stdout


def _parse_online_line(line):
    """Parse a 'Key : Value' line from DISM output."""
    line = line.strip()
    if ":" in line:
        parts = line.split(":", 1)
        key = parts[0].strip()
        val = parts[1].strip()
        return key, val
    return None, None


def _parse_section_blocks(output):
    """Parse DISM output into named sections with key:value pairs."""
    sections = {}
    current_section = None
    current_items = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        # Section headers have no colon and no leading whitespace
        # Key:value lines either have a colon or are indented
        has_colon = ":" in stripped
        is_indented = line.startswith(" ") or line.startswith("\t")
        if has_colon:
            key, val = _parse_online_line(stripped)
            if key and current_section:
                current_items[key] = val
        elif not is_indented:
            # Section header — save previous section
            if current_section and current_items:
                sections[current_section] = current_items
            current_section = stripped
            current_items = {}
        # indented lines without colons are continuation lines — ignore
    if current_section and current_items:
        sections[current_section] = current_items
    return sections


def _parse_feature_state(output):
    """Parse 'Get-Features' / 'Get-Capabilities' list output into structured data."""
    features = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                features.append(current)
                current = {}
            continue
        key, val = _parse_online_line(stripped)
        if key:
            current[key] = val
    if current:
        features.append(current)
    return features


def register_routes(app, state, require_auth):
    @app.route("/auto/dism/info", methods=["GET"])
    @require_auth
    def route_auto_dism_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/dism/ping", methods=["GET"])
    @require_auth
    def route_auto_dism_ping():
        try:
            available = _is_dism_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "DISM (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/dism/health/scan", methods=["POST"])
    @require_auth
    def route_auto_dism_health_scan():
        """Run DISM /ScanHealth — check component store corruption."""
        try:
            output = _run_dism(["/online", "/Cleanup-Image", "/ScanHealth"], timeout=120)
            # Key output: "The component store is repairable." or "No component store corruption detected."
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/dism/health/check", methods=["POST"])
    @require_auth
    def route_auto_dism_health_check():
        """Run DISM /CheckHealth — quick health check (reads existing logs only)."""
        try:
            output = _run_dism(["/online", "/Cleanup-Image", "/CheckHealth"], timeout=30)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/dism/health/restore", methods=["POST"])
    @require_auth
    def route_auto_dism_health_restore():
        """Run DISM /RestoreHealth — repair component store corruption."""
        try:
            output = _run_dism(["/online", "/Cleanup-Image", "/RestoreHealth"], timeout=300)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/dism/features", methods=["GET"])
    @require_auth
    def route_auto_dism_features():
        """List all Windows features and their state."""
        try:
            output = _run_dism(["/online", "/Get-Features", "/Format:Table"], timeout=30)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/dism/feature/enable", methods=["POST"])
    @require_auth
    def route_auto_dism_feature_enable():
        """Enable a Windows feature by name."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": _missing_field("name")}), 400
        try:
            output = _run_dism(
                ["/online", "/Enable-Feature", f"/FeatureName:{name}", "/All"],
                timeout=180,
            )
            return jsonify({"ok": True, "feature": name, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "feature": name, "error": str(e)}), 503

    @app.route("/auto/dism/feature/disable", methods=["POST"])
    @require_auth
    def route_auto_dism_feature_disable():
        """Disable a Windows feature by name."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": _missing_field("name")}), 400
        try:
            output = _run_dism(
                ["/online", "/Disable-Feature", f"/FeatureName:{name}", "/Remove"],
                timeout=180,
            )
            return jsonify({"ok": True, "feature": name, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "feature": name, "error": str(e)}), 503

    @app.route("/auto/dism/feature/state", methods=["POST"])
    @require_auth
    def route_auto_dism_feature_state():
        """Get detailed state of a specific Windows feature."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("Request body")}), 400
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": _missing_field("name")}), 400
        try:
            output = _run_dism(
                ["/online", "/Get-FeatureInfo", f"/FeatureName:{name}"],
                timeout=30,
            )
            return jsonify({"ok": True, "feature": name, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "feature": name, "error": str(e)}), 503

    @app.route("/auto/dism/packages", methods=["GET"])
    @require_auth
    def route_auto_dism_packages():
        """List all installed Windows packages."""
        try:
            output = _run_dism(["/online", "/Get-Packages", "/Format:Table"], timeout=30)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/dism/info/online", methods=["GET"])
    @require_auth
    def route_auto_dism_info_online():
        """Get current edition and version info."""
        try:
            output = _run_dism(["/online", "/Get-CurrentEdition"], timeout=15)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
