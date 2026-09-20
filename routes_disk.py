"""Disk / storage space route.

One-shot endpoint that reports free/total/used space for every fixed and
removable drive on the machine, so an AI agent can answer "is there room to
install/download X" without digging through the diagnostics report.
"""

import os
import shutil
import string
import sys

from flask import Blueprint, jsonify

from shared import COAGENT_DIR  # noqa: F401  (kept per route convention)


disk_bp = Blueprint("disk", __name__)


def _drives():
    """Return the list of drive roots to probe."""
    if sys.platform != "win32":
        return ["/"]
    roots = []
    for letter in string.ascii_uppercase:
        root = letter + ":\\"
        if os.path.exists(root):
            roots.append(root)
    return roots


def _label_and_fs(letter):
    """Best-effort volume label + filesystem via Get-Volume. Never raises."""
    if sys.platform != "win32":
        return "", ""
    try:
        import subprocess
        ps = (
            "powershell.exe -NoProfile -NonInteractive -Command "
            "\"(Get-Volume -DriveLetter {0} | Select-Object -ExpandProperty "
            "FileSystemLabel,FileSystem) -join '|'\""
        ).format(letter)
        out = subprocess.run(
            ps, capture_output=True, text=True, timeout=10, shell=True
        ).stdout.strip()
        if "|" in out:
            label, fs = out.split("|", 1)
            return label.strip(), fs.strip()
        return out.strip(), ""
    except Exception:
        return "", ""


def _collect():
    drives = []
    total_free = 0
    for root in _drives():
        try:
            stat = shutil.disk_usage(root)
        except OSError:
            continue
        total_free += stat.free
        label, fs = "", ""
        if sys.platform == "win32" and len(root) == 3:
            letter = root[0]
            label, fs = _label_and_fs(letter)
        drives.append({
            "drive": root,
            "label": label,
            "fs": fs,
            "free_bytes": int(stat.free),
            "total_bytes": int(stat.total),
            "used_bytes": int(stat.used),
            "free_gb": round(stat.free / (1024 ** 3), 2),
            "total_gb": round(stat.total / (1024 ** 3), 2),
            "used_pct": round((stat.used / stat.total) * 100, 1) if stat.total else 0.0,
        })
    drives.sort(key=lambda d: d["drive"])
    return drives, total_free


@disk_bp.route("/disk", methods=["GET"])
def route_disk():
    try:
        drives, total_free = _collect()
    except Exception as exc:
        return jsonify({"error": "{0}: {1}".format(type(exc).__name__, exc)}), 500
    return jsonify({
        "ok": True,
        "drives": drives,
        "total_free_bytes": int(total_free),
        "total_free_gb": round(total_free / (1024 ** 3), 2),
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(disk_bp)
    from shared import _wrap_registered_blueprint_routes
    _wrap_registered_blueprint_routes(app, disk_bp.name, require_auth)
