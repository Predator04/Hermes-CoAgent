# Auto-added feature: microsoft/windows (built-in) — DISKPART
# Description: diskpart.exe — Windows Disk Partition Manager.
#   List disks, volumes, and partitions. Create/delete/format partitions,
#   assign/remove drive letters, extend/shrink volumes, convert disk type
#   (MBR/GPT), manage virtual disks (VHD/VHDX), clean disks, set active
#   partitions, manage offline/online status.
# Source: Built-in Windows tool at C:\\Windows\\system32\\diskpart.exe

import os
import re
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows Disk Partition Manager — list/create/delete/format partitions, assign drive letters, manage volumes, convert disk types (MBR/GPT), manage VHDs, clean disks, set active partitions",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/diskpart",
    "added": "2026-07-19",
    "command": "diskpart /s <script>",
}


def _find_diskpart():
    """Locate diskpart.exe — typically in system32."""
    exe = shutil.which("diskpart") or shutil.which("diskpart.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\diskpart.exe",
        r"C:\Windows\SysWOW64\diskpart.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_diskpart_available():
    """Check diskpart responds by listing disks."""
    exe = _find_diskpart()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe], input=b"list disk\nexit\n",
            capture_output=True, text=False, timeout=15,
        )
        return result.returncode == 0 and len(result.stdout) > 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_diskpart_script(script_lines, timeout=30):
    """Run diskpart.exe with a list of commands, return stdout or raise."""
    exe = _find_diskpart()
    if not exe:
        raise RuntimeError("diskpart.exe not found on system")
    input_text = "\n".join(script_lines) + "\n"
    try:
        result = subprocess.run(
            [exe], input=input_text.encode("utf-16le", errors="replace"),
            capture_output=True, text=False, timeout=timeout,
        )
        stdout = result.stdout.decode("utf-16le", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-16le", errors="replace") if result.stderr else ""
    except subprocess.TimeoutExpired:
        raise RuntimeError("diskpart operation timed out")
    except OSError as e:
        raise RuntimeError(f"diskpart execution failed: {e}")
    if result.returncode != 0:
        raise RuntimeError(stderr.strip() or "diskpart returned non-zero exit code")
    return stdout


def _parse_disk_list(output):
    """Parse 'list disk' output into structured data."""
    disks = []
    lines = output.splitlines()
    # Find the table header and parse subsequent rows
    header_idx = None
    for i, line in enumerate(lines):
        if "Disk ###" in line:
            header_idx = i
            break
    if header_idx is None:
        return disks
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith("-") or "---" in line:
            continue
        if "DISKPART" in line or "list disk" in line.lower():
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 4:
            try:
                disk_num = parts[0].replace("Disk", "").strip()
                status = parts[1].strip()
                size = parts[2].strip()
                free = parts[3].strip() if len(parts) > 3 else ""
                dyn = parts[4].strip() if len(parts) > 4 else ""
                gpt = parts[5].strip() if len(parts) > 5 else ""
            except (IndexError, ValueError):
                continue
            disks.append({
                "disk": disk_num,
                "status": status,
                "size": size,
                "free": free,
                "dynamic": dyn,
                "gpt": gpt,
            })
    return disks


def _parse_volume_list(output):
    """Parse 'list volume' output into structured data."""
    volumes = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "Volume ###" in line:
            header_idx = i
            break
    if header_idx is None:
        return volumes
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith("-") or "---" in line:
            continue
        if "DISKPART" in line or "list volume" in line.lower():
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 3:
            volumes.append({
                "raw": line,
                "parts": parts,
            })
    return volumes


def _parse_partition_list(output):
    """Parse 'list partition' output."""
    partitions = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "Partition ###" in line:
            header_idx = i
            break
    if header_idx is None:
        return partitions
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line or line.startswith("-") or "---" in line:
            continue
        if "DISKPART" in line or "list partition" in line.lower():
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 3:
            partitions.append({
                "raw": line,
                "parts": parts,
            })
    return partitions


def register_routes(app, state, require_auth):
    @app.route("/auto/diskpart/info", methods=["GET"])
    @require_auth
    def route_auto_diskpart_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/diskpart/ping", methods=["GET"])
    @require_auth
    def route_auto_diskpart_ping():
        avail = _is_diskpart_available()
        return jsonify({"ok": True, "available": avail, "exe": _find_diskpart()})

    @app.route("/auto/diskpart/list-disks", methods=["GET"])
    @require_auth
    def route_auto_diskpart_list_disks():
        """List all physical disks attached to the system."""
        try:
            output = _run_diskpart_script(["list disk", "exit"], timeout=15)
            parsed = _parse_disk_list(output)
            return jsonify({"ok": True, "disks": parsed, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/diskpart/list-volumes", methods=["GET"])
    @require_auth
    def route_auto_diskpart_list_volumes():
        """List all volumes (partitions with drive letters/mounts)."""
        try:
            output = _run_diskpart_script(["list volume", "exit"], timeout=15)
            parsed = _parse_volume_list(output)
            return jsonify({"ok": True, "volumes": parsed, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/diskpart/list-partitions", methods=["POST"])
    @require_auth
    def route_auto_diskpart_list_partitions():
        """List partitions on a specific disk."""
        body = _json_body()
        disk_num = (body.get("disk") or "0").strip()
        if not disk_num.isdigit():
            return jsonify({"ok": False, "error": "disk must be a numeric index"}), 400
        try:
            output = _run_diskpart_script(
                [f"select disk {disk_num}", "list partition", "exit"], timeout=15
            )
            parsed = _parse_partition_list(output)
            return jsonify({"ok": True, "disk": disk_num, "partitions": parsed, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "disk": disk_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/disk-detail", methods=["POST"])
    @require_auth
    def route_auto_diskpart_disk_detail():
        """Get detailed info about a specific disk."""
        body = _json_body()
        disk_num = (body.get("disk") or "0").strip()
        if not disk_num.isdigit():
            return jsonify({"ok": False, "error": "disk must be a numeric index"}), 400
        try:
            output = _run_diskpart_script(
                [f"select disk {disk_num}", "detail disk", "exit"], timeout=15
            )
            return jsonify({"ok": True, "disk": disk_num, "detail": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "disk": disk_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/clean-disk", methods=["POST"])
    @require_auth
    def route_auto_diskpart_clean_disk():
        """Remove all partitions from a disk (DESTRUCTIVE — requires confirmation)."""
        body = _json_body()
        disk_num = (body.get("disk") or "").strip()
        confirm = body.get("confirm", False)
        if not disk_num:
            return _missing_field("disk")
        if not disk_num.isdigit():
            return jsonify({"ok": False, "error": "disk must be a numeric index"}), 400
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. This is DESTRUCTIVE and removes ALL data on the disk."
            }), 400
        try:
            output = _run_diskpart_script(
                [f"select disk {disk_num}", "clean", "exit"], timeout=30
            )
            return jsonify({"ok": True, "disk": disk_num, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "disk": disk_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/convert-gpt", methods=["POST"])
    @require_auth
    def route_auto_diskpart_convert_gpt():
        """Convert a disk from MBR to GPT (DESTRUCTIVE — requires confirmation)."""
        body = _json_body()
        disk_num = (body.get("disk") or "").strip()
        confirm = body.get("confirm", False)
        if not disk_num:
            return _missing_field("disk")
        if not disk_num.isdigit():
            return jsonify({"ok": False, "error": "disk must be a numeric index"}), 400
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. Converts disk format (MBR->GPT)."
            }), 400
        try:
            output = _run_diskpart_script(
                [f"select disk {disk_num}", "convert gpt", "exit"], timeout=30
            )
            return jsonify({"ok": True, "disk": disk_num, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "disk": disk_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/create-partition", methods=["POST"])
    @require_auth
    def route_auto_diskpart_create_partition():
        """Create a new partition on a disk. Specify size in MB (optional)."""
        body = _json_body()
        disk_num = (body.get("disk") or "").strip()
        size_mb = body.get("size_mb")
        partition_type = body.get("type", "primary").strip().lower()
        if not disk_num:
            return _missing_field("disk")
        if not disk_num.isdigit():
            return jsonify({"ok": False, "error": "disk must be a numeric index"}), 400
        if partition_type not in ("primary", "extended", "logical"):
            partition_type = "primary"
        if size_mb not in (None, ""):
            try:
                size_mb = int(size_mb)
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": "size_mb must be an integer"}), 400
            if size_mb < 1 or size_mb > 1_000_000_000:
                return jsonify({"ok": False, "error": "size_mb must be between 1 and 1000000000"}), 400
        commands = [f"select disk {disk_num}"]
        if size_mb:
            commands.append(f"create partition {partition_type} size={size_mb}")
        else:
            commands.append(f"create partition {partition_type}")
        commands.append("exit")
        try:
            output = _run_diskpart_script(commands, timeout=30)
            return jsonify({"ok": True, "disk": disk_num, "type": partition_type, "size_mb": size_mb, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "disk": disk_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/format-volume", methods=["POST"])
    @require_auth
    def route_auto_diskpart_format_volume():
        """Format a volume with specified filesystem (DESTRUCTIVE — requires confirmation)."""
        body = _json_body()
        volume_num = (body.get("volume") or "").strip()
        fs = (body.get("filesystem") or "NTFS").strip().upper()
        label = (body.get("label") or "").strip()
        quick = body.get("quick", True)
        confirm = body.get("confirm", False)
        if not volume_num:
            return _missing_field("volume")
        if not volume_num.isdigit():
            return jsonify({"ok": False, "error": "volume must be a numeric index"}), 400
        if fs not in ("NTFS", "FAT", "FAT32", "EXFAT", "REFS", "UDF"):
            return jsonify({"ok": False, "error": f"unsupported filesystem '{fs}'"}), 400
        if label and not re.fullmatch(r"[A-Za-z0-9 _\-.]{1,32}", label):
            return jsonify({"ok": False, "error": "label may only contain letters, digits, spaces, and ._- (max 32 chars)"}), 400
        if not confirm:
            return jsonify({
                "ok": False,
                "error": "Confirmation required — set 'confirm: true' to proceed. Formatting is DESTRUCTIVE."
            }), 400
        commands = [f"select volume {volume_num}"]
        quick_flag = "quick" if quick else ""
        if label:
            commands.append(f"format fs={fs} label=\"{label}\" {quick_flag}".strip())
        else:
            commands.append(f"format fs={fs} {quick_flag}".strip())
        commands.append("exit")
        try:
            output = _run_diskpart_script(commands, timeout=120)
            return jsonify({"ok": True, "volume": volume_num, "filesystem": fs, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/assign-letter", methods=["POST"])
    @require_auth
    def route_auto_diskpart_assign_letter():
        """Assign a drive letter to a volume."""
        body = _json_body()
        volume_num = (body.get("volume") or "").strip()
        letter = (body.get("letter") or "").strip().upper().replace(":", "")
        if not volume_num:
            return _missing_field("volume")
        if not volume_num.isdigit():
            return jsonify({"ok": False, "error": "volume must be a numeric index"}), 400
        if not letter or len(letter) != 1 or letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            return jsonify({"ok": False, "error": "Invalid drive letter"}), 400
        try:
            output = _run_diskpart_script(
                [f"select volume {volume_num}", f"assign letter={letter}", "exit"], timeout=15
            )
            return jsonify({"ok": True, "volume": volume_num, "letter": letter, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume_num, "error": str(e)}), 503

    @app.route("/auto/diskpart/remove-letter", methods=["POST"])
    @require_auth
    def route_auto_diskpart_remove_letter():
        """Remove a drive letter from a volume (make it hidden)."""
        body = _json_body()
        volume_num = (body.get("volume") or "").strip()
        letter = (body.get("letter") or "").strip().upper().replace(":", "")
        if not volume_num:
            return _missing_field("volume")
        if not volume_num.isdigit():
            return jsonify({"ok": False, "error": "volume must be a numeric index"}), 400
        if not letter or len(letter) != 1 or letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            return jsonify({"ok": False, "error": "Invalid drive letter"}), 400
        try:
            output = _run_diskpart_script(
                [f"select volume {volume_num}", f"remove letter={letter}", "exit"], timeout=15
            )
            return jsonify({"ok": True, "volume": volume_num, "letter": letter, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "volume": volume_num, "error": str(e)}), 503
