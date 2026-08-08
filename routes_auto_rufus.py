# Auto-added feature: pbatard/rufus (37019 stars)
# The Reliable USB Formatting Utility
# Source: https://github.com/pbatard/rufus
# CLI: rufus.exe /create /iso:<path> /drive:<letter> /target:<label> /volume_label:<label> /no_2fa

import os
import re
import shutil
import subprocess
import tempfile

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "pbatard/rufus",
    "stars": 37019,
    "desc": "The Reliable USB Formatting Utility. Create bootable USB drives from ISOs, "
             "format USB drives, create Windows To Go drives, and more.",
    "url": "https://github.com/pbatard/rufus",
    "added": "2026-07-24",
    "cli": "rufus.exe /create /iso:\"<path>\" /drive:<letter>",
    "cli_params": [
        "/create", "/iso:", "/drive:", "/target:layout",
        "/volume_label:", "/no_2fa",
    ],
}


def _find_rufus():
    """Locate rufus.exe on this system."""
    candidates = [
        shutil.which("rufus.exe"),
        os.path.expanduser(r"~\Desktop\rufus\rufus.exe"),
        os.path.expanduser(r"~\Downloads\rufus.exe"),
        os.path.expanduser(r"~\rufus.exe"),
        r"C:\Program Files\Rufus\rufus.exe",
        r"C:\Program Files (x86)\Rufus\rufus.exe",
        r"C:\Rufus\rufus.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _list_usb_drives():
    """List USB drives using Python stdlib + WMIC fallback."""
    drives = []
    # Try using Python's os.listdrives or string.uppercase
    if hasattr(os, "listdrives"):
        drive_letters = list(os.listdrives())
    else:
        import string
        drive_letters = [f"{l}:\\" for l in string.ascii_uppercase if os.path.exists(f"{l}:\\")]

    for d in drive_letters:
        try:
            if not os.path.exists(d):
                continue
            drive_type = 0
            try:
                import ctypes
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(d)
            except Exception:
                pass
            # DRIVE_REMOVABLE = 2, DRIVE_FIXED = 3, DRIVE_CDROM = 5, DRIVE_RAMDISK = 6
            type_names = {2: "removable", 3: "fixed", 4: "remote", 5: "cdrom", 6: "ramdisk"}
            dtype_name = type_names.get(drive_type, f"unknown({drive_type})")

            usage = shutil.disk_usage(d)
            drives.append({
                "drive": d,
                "type": dtype_name,
                "is_usb": drive_type == 2,
                "total_gb": round(usage.total / (1024**3), 1),
                "free_gb": round(usage.free / (1024**3), 1),
                "used_gb": round((usage.total - usage.free) / (1024**3), 1),
            })
        except Exception:
            pass

    return drives


def _list_isos(search_paths=None):
    """Find ISO files on common download locations."""
    if search_paths is None:
        search_paths = [
            os.path.expanduser(r"~\Desktop"),
            os.path.expanduser(r"~\Downloads"),
            os.path.expanduser(r"~\Documents"),
            os.path.expanduser(r"~\ISOs"),
            r"C:\ISOs",
        ]
    isos = []
    for base in search_paths:
        if not os.path.isdir(base):
            continue
        try:
            for f in os.listdir(base):
                if f.lower().endswith(".iso") or f.lower().endswith(".wim"):
                    path = os.path.join(base, f)
                    size_mb = round(os.path.getsize(path) / (1024**2), 1)
                    isos.append({
                        "path": path,
                        "name": f,
                        "size_mb": size_mb,
                        "location": base,
                    })
        except Exception:
            pass
    return isos


def register_routes(app, state, require_auth):
    @app.route("/auto/rufus/info", methods=["GET"])
    @require_auth
    def route_auto_rufus_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/rufus/ping", methods=["GET"])
    @require_auth
    def route_auto_rufus_ping():
        rufus_path = _find_rufus()
        return jsonify({
            "status": "ok" if rufus_path else "unavailable",
            "feature": "pbatard/rufus",
            "installed": rufus_path is not None,
            "path": rufus_path,
        })

    @app.route("/auto/rufus/drives", methods=["GET"])
    @require_auth
    def route_auto_rufus_drives():
        """List available drives with type info (removable/fixed)."""
        try:
            drives = _list_usb_drives()
            return jsonify({"ok": True, "drives": drives})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/auto/rufus/isos", methods=["GET"])
    @require_auth
    def route_auto_rufus_isos():
        """List ISO/WIM files found on common search paths."""
        try:
            isos = _list_isos()
            return jsonify({
                "ok": True,
                "count": len(isos),
                "isos": sorted(isos, key=lambda x: -x["size_mb"]),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/auto/rufus/create", methods=["POST"])
    @require_auth
    def route_auto_rufus_create():
        """Create a bootable USB drive using Rufus CLI."""
        rufus_path = _find_rufus()
        if not rufus_path:
            return jsonify({
                "ok": False,
                "error": "Rufus is not installed on this system. "
                         "Download from https://rufus.ie"
            }), 503

        try:
            body = _json_body()
            if body is None:
                return jsonify({"ok": False, "error": _missing_field("request body")}), 400
        except Exception:
            return jsonify({"ok": False, "error": _missing_field("request body")}), 400

        iso_path = body.get("iso_path", "")
        drive_letter = body.get("drive", "")
        volume_label = body.get("volume_label", "")
        target = body.get("target", "")  # e.g., "UEFI", "BIOS", "MBR", "GPT"

        if not iso_path or not os.path.isfile(iso_path):
            return jsonify({"ok": False, "error": "iso_path must point to a valid ISO file"}), 400
        if not drive_letter:
            return jsonify({"ok": False, "error": _missing_field("drive (e.g. 'F')")}), 400

        # Strip any trailing backslash or colon from drive letter
        drive_letter = drive_letter.strip(":\\ ")

        cmd_parts = [rufus_path, "/create", f"/iso:{iso_path}", f"/drive:{drive_letter}"]
        if volume_label:
            cmd_parts.append(f"/volume_label:{volume_label}")
        if target:
            allowed_targets = ["UEFI", "BIOS", "MBR", "GPT", "UEFI-CSM"]
            if target not in allowed_targets:
                return jsonify({"ok": False, "error": f"target must be one of {allowed_targets}"}), 400
            cmd_parts.append(f"/target:{target}")

        try:
            _log(f"[rufus] Running: {' '.join(cmd_parts)}")
            result = subprocess.run(
                cmd_parts,
                capture_output=True, text=True, timeout=300
            )
            return jsonify({
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "Command timed out (300s)"}), 504
        except OSError as e:
            return jsonify({"ok": False, "error": f"OS error: {e}"}), 502
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
