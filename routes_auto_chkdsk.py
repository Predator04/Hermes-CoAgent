# Auto-added feature: microsoft/windows (built-in) — CHKDSK
# Description: chkdsk.exe — Check Disk utility for Windows.
#   Verify file system integrity, discover bad sectors, repair disk errors,
#   perform offline scans, view file system info (NTFS, FAT32, exFAT),
#   force dismount before scan, schedule scans for next reboot.
# Source: Built-in Windows tool at C:\\Windows\\system32\\chkdsk.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Check Disk — verify file system integrity, repair disk errors, discover bad sectors, perform offline scans, manage scheduled scans for next boot",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/chkdsk",
    "added": "2026-07-19",
    "command": "chkdsk <volume:> [/F] [/R] [/X]",
}


def _find_chkdsk():
    """Locate chkdsk.exe — typically in system32."""
    exe = shutil.which("chkdsk") or shutil.which("chkdsk.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\chkdsk.exe",
        r"C:\Windows\SysWOW64\chkdsk.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_chkdsk_available():
    """Check chkdsk responds by running a quick read-only scan (no repair)."""
    exe = _find_chkdsk()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "C:"], capture_output=True, text=True, timeout=15)
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_chkdsk(args, timeout=120):
    """Run chkdsk.exe with given args, return parsed output or raise."""
    exe = _find_chkdsk()
    if not exe:
        raise RuntimeError("chkdsk.exe not found on system")
    try:
        result = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("chkdsk operation timed out")
    except OSError as e:
        raise RuntimeError(f"chkdsk execution failed: {e}")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "chkdsk returned non-zero exit code")
    return result.stdout


def _parse_chkdsk_output(output):
    """Extract key statistics from chkdsk output."""
    result = {"raw_output": output, "parsed": {}}
    patterns = [
        ("files_total", r"(\d+)\s+file\w+\s+processed", 1),
        ("folders_total", r"(\d+)\s+((folder|directory)\w+)\s+processed", 1),
        ("total_disk_space", r"(\d[\d,]*)\s+KB\s+total\s+disk\s+space", 1),
        ("bad_sectors", r"(\d+)\s+KB\s+in\s+bad\s+sectors", 1),
        ("in_use_files", r"(\d+)\s+file\w+\s+indexed", 1),
        ("log_file_size", r"(\d+)\s+KB\s+in\s+log\s+file", 1),
        ("available_space", r"(\d[\d,]*)\s+KB\s+available", 1),
        ("allocation_units", r"(\d[\d,]*)\s+allocation\s+units", 1),
        ("errors_found", r"(\d+)\s+(error|problem)\w+\s+found", 1),
        ("bad_in_user_file", r"(\d+)\s+KB\s+in\s+bad\s+sectors\s+in\s+user\s+files", 1),
        ("file_system_type", r"(The type of the file system is\s*:\s*(\w+))", 2),
        ("volume_name", r"(Volume label is\s*(\w[\w ]*)\s*\.)", 2),
        ("stage", r"(Stage\s+\d+:\s+.+)", 1),
        ("fs_state", r"(Windows has scanned the file system and found no problems|Windows has found problems with the file system)", 1),
    ]
    for key, pattern, group in patterns:
        m = re.search(pattern, output, re.IGNORECASE)
        if m:
            val = m.group(group).strip()
            try:
                val = int(val.replace(",", "").replace(".", ""))
            except (ValueError, AttributeError):
                pass
            result["parsed"][key] = val
    return result


def register_routes(app, state, require_auth):
    @app.route("/auto/chkdsk/info", methods=["GET"])
    @require_auth
    def route_auto_chkdsk_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/chkdsk/ping", methods=["GET"])
    @require_auth
    def route_auto_chkdsk_ping():
        avail = _is_chkdsk_available()
        return jsonify({"ok": True, "available": avail, "exe": _find_chkdsk()})

    @app.route("/auto/chkdsk/scan", methods=["POST"])
    @require_auth
    def route_auto_chkdsk_scan():
        """Run a read-only scan on a volume (no repair) — safe, non-destructive."""
        body = _json_body()
        volume = (body.get("volume") or "C:").strip().rstrip("\\")
        try:
            output = _run_chkdsk([volume], timeout=120)
            parsed = _parse_chkdsk_output(output)
            return jsonify({"ok": True, "volume": volume, "parsed": parsed})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume, "error": str(e)}), 503

    @app.route("/auto/chkdsk/repair", methods=["POST"])
    @require_auth
    def route_auto_chkdsk_repair():
        """Schedule a repair scan (/F) — may require volume dismount or next boot."""
        body = _json_body()
        volume = (body.get("volume") or "C:").strip().rstrip("\\")
        try:
            output = _run_chkdsk([volume, "/F"], timeout=300)
            parsed = _parse_chkdsk_output(output)
            return jsonify({"ok": True, "volume": volume, "parsed": parsed})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume, "error": str(e)}), 503

    @app.route("/auto/chkdsk/thorough", methods=["POST"])
    @require_auth
    def route_auto_chkdsk_thorough():
        """Run a thorough scan (/R) — locates bad sectors and recovers readable info."""
        body = _json_body()
        volume = (body.get("volume") or "C:").strip().rstrip("\\")
        try:
            output = _run_chkdsk([volume, "/R"], timeout=600)
            parsed = _parse_chkdsk_output(output)
            return jsonify({"ok": True, "volume": volume, "parsed": parsed})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume, "error": str(e)}), 503

    @app.route("/auto/chkdsk/force-dismount", methods=["POST"])
    @require_auth
    def route_auto_chkdsk_force_dismount():
        """Force dismount before scan (/X) — useful for non-system volumes."""
        body = _json_body()
        volume = (body.get("volume") or "D:").strip().rstrip("\\")
        try:
            output = _run_chkdsk([volume, "/X", "/F"], timeout=300)
            parsed = _parse_chkdsk_output(output)
            return jsonify({"ok": True, "volume": volume, "parsed": parsed})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume, "error": str(e)}), 503

    @app.route("/auto/chkdsk/schedule", methods=["POST"])
    @require_auth
    def route_auto_chkdsk_schedule():
        """Schedule chkdsk to run on next boot (for system volumes in use)."""
        body = _json_body()
        volume = (body.get("volume") or "C:").strip().rstrip("\\")
        try:
            output = _run_chkdsk([volume, "/F", "/R", "/OfflineScanAndFix"], timeout=30)
            parsed = _parse_chkdsk_output(output)
            return jsonify({"ok": True, "volume": volume, "parsed": parsed})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume, "error": str(e)}), 503

    @app.route("/auto/chkdsk/volumes", methods=["GET"])
    @require_auth
    def route_auto_chkdsk_volumes():
        """List available volumes via a single wmic logicaldisk query."""
        try:
            result = subprocess.run(
                ["wmic", "logicaldisk", "get", "DeviceID,VolumeName,FileSystem,Size,FreeSpace", "/format:csv"],
                capture_output=True, text=True, timeout=15,
            )
            drives = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("Node") or line.startswith(","):
                    continue
                parts = line.split(",")
                if len(parts) >= 3:
                    drives.append({
                        "volume": parts[1].strip() if len(parts) > 1 else "",
                        "filesystem": parts[2].strip() if len(parts) > 2 else "",
                        "free_bytes": parts[3].strip() if len(parts) > 3 else "",
                        "size_bytes": parts[4].strip() if len(parts) > 4 else "",
                        "label": parts[5].strip() if len(parts) > 5 else "",
                    })
            return jsonify({"ok": True, "volumes": drives})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
