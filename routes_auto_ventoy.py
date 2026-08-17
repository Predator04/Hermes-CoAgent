# Auto-added feature: ventoy/Ventoy (78216 stars)
# Open source tool to create bootable USB drive for ISO/WIM/IMG/VHD(x)/EFI files
# Source: https://github.com/ventoy/Ventoy
# CLI: Ventoy2Disk.exe VTOYCLI /I|/U <disk> [options]

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ventoy/Ventoy",
    "stars": 78216,
    "desc": "Open source tool to create bootable USB drive for ISO/WIM/IMG/VHD(x)/EFI files. "
             "With Ventoy, you don't need to format the disk over and over, just copy ISO files to the USB drive and boot them.",
    "url": "https://github.com/ventoy/Ventoy",
    "added": "2026-07-24",
    "cli": "Ventoy2Disk.exe VTOYCLI /I|/U <disk> [options]",
    "cli_params": [
        "VTOYCLI", "/I", "/U", "/GPT", "/NOSB",
        "/Drive:", "/PhyDrive:",
    ],
}


def _find_ventoy():
    """Locate Ventoy2Disk.exe on this system."""
    candidates = [
        shutil.which("Ventoy2Disk.exe"),
        os.path.expanduser(r"~\Desktop\Ventoy2Disk\Ventoy2Disk.exe"),
        os.path.expanduser(r"~\Downloads\Ventoy2Disk\Ventoy2Disk.exe"),
        os.path.expanduser(r"~\Ventoy\Ventoy2Disk.exe"),
        r"C:\Program Files\Ventoy\Ventoy2Disk.exe",
        r"C:\Ventoy\Ventoy2Disk.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _list_volumes():
    """List available volumes/drives using Python stdlib."""
    volumes = []
    if hasattr(os, "listdrives"):
        for d in os.listdrives():
            try:
                usage = shutil.disk_usage(d)
                volumes.append({
                    "drive": d,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "used_gb": round((usage.total - usage.free) / (1024**3), 1),
                })
            except Exception:
                volumes.append({"drive": d, "error": "cannot query"})
    else:
        import string
        for letter in string.ascii_uppercase:
            d = f"{letter}:\\"
            if os.path.exists(d):
                try:
                    usage = shutil.disk_usage(d)
                    volumes.append({
                        "drive": d,
                        "total_gb": round(usage.total / (1024**3), 1),
                        "free_gb": round(usage.free / (1024**3), 1),
                        "used_gb": round((usage.total - usage.free) / (1024**3), 1),
                    })
                except Exception:
                    volumes.append({"drive": d, "error": "cannot query"})
    return volumes


def register_routes(app, state, require_auth):
    @app.route("/auto/ventoy/info", methods=["GET"])
    @require_auth
    def route_auto_ventoy_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/ventoy/ping", methods=["GET"])
    @require_auth
    def route_auto_ventoy_ping():
        ventoy_path = _find_ventoy()
        return jsonify({
            "status": "ok" if ventoy_path else "unavailable",
            "feature": "ventoy/Ventoy",
            "installed": ventoy_path is not None,
            "path": ventoy_path,
        })

    @app.route("/auto/ventoy/volumes", methods=["GET"])
    @require_auth
    def route_auto_ventoy_volumes():
        """List available disk volumes/drives that Ventoy could target."""
        try:
            volumes = _list_volumes()
            return jsonify({"ok": True, "volumes": volumes})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/auto/ventoy/status", methods=["GET"])
    @require_auth
    def route_auto_ventoy_status():
        """Check if a disk looks like a Ventoy drive by looking for the Ventoy partition label."""
        ventoy_path = _find_ventoy()
        volumes = _list_volumes()
        ventoy_disks = []
        for vol in volumes:
            d = vol["drive"]
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                volume_buf = ctypes.create_unicode_buffer(256)
                fs_buf = ctypes.create_unicode_buffer(256)
                success = kernel32.GetVolumeInformationW(
                    d, volume_buf, 256, None, None, None, fs_buf, 256
                )
                if success:
                    label = volume_buf.value
                    fs = fs_buf.value
                    if "VENTOY" in label.upper():
                        ventoy_disks.append({
                            "drive": d,
                            "label": label,
                            "filesystem": fs,
                        })
            except Exception:
                pass
        return jsonify({
            "ok": True,
            "installed": ventoy_path is not None,
            "ventoy_path": ventoy_path,
            "ventoy_disks_found": len(ventoy_disks),
            "ventoy_disks": ventoy_disks if ventoy_disks else None,
        })

    @app.route("/auto/ventoy/install", methods=["POST"])
    @require_auth
    def route_auto_ventoy_install():
        """Install Ventoy to a target disk using Ventoy2Disk.exe CLI."""
        ventoy_path = _find_ventoy()
        if not ventoy_path:
            return jsonify({
                "ok": False,
                "error": "Ventoy is not installed on this system. "
                         "Download from https://github.com/ventoy/Ventoy/releases"
            }), 503

        try:
            body = _json_body()
            if body is None:
                return jsonify({"ok": False, "error": _missing_field("request body")}), 400
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("request body")}), 400

        disk = body.get("disk", "")
        cmd = body.get("cmd", "I")  # I = install, U = update
        gpt = body.get("gpt", False)
        no_sb = body.get("no_secure_boot", False)

        if not disk:
            return jsonify({"ok": False, "error": _missing_field("disk (e.g. /Drive:F: or /PhyDrive:1)")}), 400
        if not isinstance(disk, str) or not re.match(r'^(/Drive:[A-Za-z]:|/PhyDrive:\d{1,3})$', disk):
            return jsonify({"ok": False, "error": "disk must be /Drive:X: or /PhyDrive:N"}), 400
        # Destructive operation guard: require explicit confirmation and refuse the OS disk.
        if body.get("confirm") is not True:
            return jsonify({"ok": False, "error": "confirm must be true to reformat a disk"}), 400
        if disk == "/PhyDrive:0":
            return jsonify({"ok": False, "error": "Refusing to target /PhyDrive:0 (system disk)"}), 400
        if not isinstance(cmd, str):
            return jsonify({"ok": False, "error": "cmd must be 'I' or 'U'"}), 400
        if cmd.upper() not in ("I", "U"):
            return jsonify({"ok": False, "error": "cmd must be 'I' (install) or 'U' (update)"}), 400

        # Build command args
        cmd_parts = [ventoy_path, "VTOYCLI", f"/{cmd.upper()}", str(disk)]
        if gpt:
            cmd_parts.append("/GPT")
        if no_sb:
            cmd_parts.append("/NOSB")

        try:
            _log(f"[ventoy] Running: {' '.join(cmd_parts)}")
            result = subprocess.run(
                cmd_parts,
                capture_output=True, text=True, timeout=120
            )
            return jsonify({
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "Command timed out (120s)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
