# Auto-added feature: microsoft/windows (built-in) — vssadmin
# Description: vssadmin.exe — Volume Shadow Copy Service administrative CLI.
#   List/create/delete volume shadow copies (snapshots), list shadow copy providers,
#   storage associations, eligible volumes, and subscribed VSS writers.
#   Manage shadow copy storage resize operations.
# Source: Built-in Windows tool at C:\Windows\system32\vssadmin.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Volume Shadow Copy Service administration — list/create/delete volume shadow copies (snapshots), list providers, storage associations, eligible volumes, subscribed VSS writers, and resize shadow copy storage",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/vssadmin",
    "added": "2026-07-18",
    "command": "vssadmin <subcommand>",
}

# Regex for parsing vssadmin output blocks
SHADOW_ID_RE = re.compile(r"^\s*Shadow Copy ID:\s*(.+)$")
SHADOW_VOLUME_RE = re.compile(r"^\s*Shadow Copy Volume:\s*(.+)$")
SHADOW_SET_RE = re.compile(r"^\s*Shadow Copy Set:\s*(.+)$")
PROVIDER_NAME_RE = re.compile(r"^\s*Provider name:\s*'(.*)'")
PROVIDER_TYPE_RE = re.compile(r"^\s*Provider type:\s*(.+)$")
PROVIDER_ID_RE = re.compile(r"^\s*Provider ID:\s*{(.+)}")
VOLUME_PATH_RE = re.compile(r"^\s*Volume Path:\s*(.+)$")
VOLUME_NAME_RE = re.compile(r"^\s*Volume Name:\s*(.+)$")
WRITER_NAME_RE = re.compile(r"^\s*Writer name:\s*'(.+)'")
WRITER_ID_RE = re.compile(r"^\s*Writer Id:\s*{(.+)}")
WRITER_STATE_RE = re.compile(r"^\s*Writer State:\s*(.+)$")
STORAGE_USED_RE = re.compile(r"^\s*Used Shadow Copy Storage space:\s*(.+)$")
STORAGE_ALLOC_RE = re.compile(r"^\s*Allocated Shadow Copy Storage space:\s*(.+)$")
STORAGE_LIMIT_RE = re.compile(r"^\s*Maximum Shadow Copy Storage space:\s*(.+)$")


def _find_vssadmin():
    """Locate vssadmin.exe."""
    exe = shutil.which("vssadmin") or shutil.which("vssadmin.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\vssadmin.exe",
        r"C:\Windows\SysWOW64\vssadmin.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_vssadmin_available():
    """Check vssadmin responds."""
    exe = _find_vssadmin()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "list", "providers"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_vssadmin(args, timeout=30):
    """Run vssadmin.exe with given args, return parsed output or raise."""
    exe = _find_vssadmin()
    if not exe:
        raise RuntimeError("vssadmin.exe not found on system")
    try:
        result = subprocess.run(
            [exe] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("vssadmin operation timed out")
    except OSError as e:
        raise RuntimeError(f"vssadmin execution failed: {e}")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "vssadmin returned non-zero exit code")
    return result.stdout


def _parse_shadow_copies(output):
    """Parse List Shadows output into structured list."""
    copies = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                copies.append(current)
                current = {}
            continue
        m = SHADOW_ID_RE.match(stripped)
        if m:
            current["shadow_copy_id"] = m.group(1).strip()
            continue
        m = SHADOW_VOLUME_RE.match(stripped)
        if m:
            current["shadow_copy_volume"] = m.group(1).strip()
            continue
        m = SHADOW_SET_RE.match(stripped)
        if m:
            current["shadow_copy_set"] = m.group(1).strip()
            continue
        if current and ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        copies.append(current)
    return copies


def _parse_providers(output):
    """Parse List Providers output into structured list."""
    providers = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                providers.append(current)
                current = {}
            continue
        m = PROVIDER_NAME_RE.match(stripped)
        if m:
            current["name"] = m.group(1).strip()
            continue
        m = PROVIDER_TYPE_RE.match(stripped)
        if m:
            current["provider_type"] = m.group(1).strip()
            continue
        m = PROVIDER_ID_RE.match(stripped)
        if m:
            current["provider_id"] = "{" + m.group(1).strip() + "}"
            continue
        if current and ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        providers.append(current)
    return providers


def _parse_writers(output):
    """Parse List Writers output into structured list."""
    writers = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current and "writer_name" in current:
                writers.append(current)
                current = {}
            continue
        m = WRITER_NAME_RE.match(stripped)
        if m:
            current["writer_name"] = m.group(1).strip()
            continue
        m = WRITER_ID_RE.match(stripped)
        if m:
            current["writer_id"] = "{" + m.group(1).strip() + "}"
            continue
        m = WRITER_STATE_RE.match(stripped)
        if m:
            current["writer_state"] = m.group(1).strip()
            continue
    if current and "writer_name" in current:
        writers.append(current)
    return writers


def _parse_volumes(output):
    """Parse List Volumes output into structured list."""
    volumes = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                volumes.append(current)
                current = {}
            continue
        m = VOLUME_PATH_RE.match(stripped)
        if m:
            current["volume_path"] = m.group(1).strip()
            continue
        m = VOLUME_NAME_RE.match(stripped)
        if m:
            current["volume_name"] = m.group(1).strip()
            continue
        if current and ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        volumes.append(current)
    return volumes


def _parse_storage(output):
    """Parse List ShadowStorage output into structured list."""
    storage_entries = []
    current = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                storage_entries.append(current)
                current = {}
            continue
        m = STORAGE_USED_RE.match(stripped)
        if m:
            current["used_space"] = m.group(1).strip()
            continue
        m = STORAGE_ALLOC_RE.match(stripped)
        if m:
            current["allocated_space"] = m.group(1).strip()
            continue
        m = STORAGE_LIMIT_RE.match(stripped)
        if m:
            current["max_space"] = m.group(1).strip()
            continue
        m = VOLUME_PATH_RE.match(stripped)
        if m:
            current["volume_path"] = m.group(1).strip()
            continue
        m = VOLUME_NAME_RE.match(stripped)
        if m:
            current["volume_name"] = m.group(1).strip()
            continue
        if current and ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if key and val:
                current[key] = val
    if current:
        storage_entries.append(current)
    return storage_entries


def register_routes(app, state, require_auth):
    @app.route("/auto/vssadmin/info", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/vssadmin/ping", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_ping():
        try:
            available = _is_vssadmin_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "vssadmin (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/vssadmin/shadows", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_shadows():
        """List all existing volume shadow copies."""
        try:
            output = _run_vssadmin(["list", "shadows"], timeout=15)
            copies = _parse_shadow_copies(output)
            raw = output
            return jsonify({"ok": True, "shadows": copies, "count": len(copies), "raw": raw})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/delete_shadows", methods=["POST"])
    @require_auth
    def route_auto_vssadmin_delete_shadows():
        """Delete volume shadow copies. Optionally specify volume and shadow copy ID."""
        body = _json_body()
        if not isinstance(body, dict):
            return _missing_field("body")
        try:
            args = ["delete", "shadows"]
            vol = (body.get("volume") or "").strip()
            shadow_id = (body.get("shadow_id") or "").strip()
            if shadow_id:
                args.extend([f"/Shadow={shadow_id}"])
            elif vol:
                args.extend([f"/For={vol}"])
            elif body.get("all") is True:
                args.append("/All")
            else:
                return jsonify({"error": "Missing required field: volume or shadow_id (or set all=true to delete all shadow copies)"}), 400
            # quiet mode to avoid interactive prompt
            args.append("/Quiet")
            output = _run_vssadmin(args, timeout=30)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/providers", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_providers():
        """List registered volume shadow copy providers."""
        try:
            output = _run_vssadmin(["list", "providers"], timeout=15)
            providers = _parse_providers(output)
            return jsonify({"ok": True, "providers": providers, "count": len(providers), "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/storage", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_storage():
        """List volume shadow copy storage associations."""
        try:
            output = _run_vssadmin(["list", "shadowstorage"], timeout=15)
            storage_entries = _parse_storage(output)
            return jsonify({"ok": True, "storage": storage_entries, "count": len(storage_entries), "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/volumes", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_volumes():
        """List volumes eligible for shadow copies."""
        try:
            output = _run_vssadmin(["list", "volumes"], timeout=15)
            volumes = _parse_volumes(output)
            return jsonify({"ok": True, "volumes": volumes, "count": len(volumes), "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/writers", methods=["GET"])
    @require_auth
    def route_auto_vssadmin_writers():
        """List subscribed volume shadow copy writers with their state."""
        try:
            output = _run_vssadmin(["list", "writers"], timeout=15)
            writers = _parse_writers(output)
            return jsonify({"ok": True, "writers": writers, "count": len(writers), "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/vssadmin/resize_storage", methods=["POST"])
    @require_auth
    def route_auto_vssadmin_resize_storage():
        """Resize shadow copy storage for a volume."""
        body = _json_body()
        if not isinstance(body, dict):
            return _missing_field("body")
        volume = (body.get("volume") or "").strip()
        if not volume:
            return _missing_field("volume")
        max_size = (body.get("max_size") or "").strip()
        if not max_size:
            return _missing_field("max_size")
        try:
            output = _run_vssadmin(
                ["resize", "shadowstorage", f"/For={volume}", f"/On={volume}", f"/MaxSize={max_size}"],
                timeout=30,
            )
            return jsonify({"ok": True, "volume": volume, "max_size": max_size, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
