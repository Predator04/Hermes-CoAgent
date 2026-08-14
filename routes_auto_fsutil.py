# Auto-added feature: microsoft/windows (built-in) — FsUtil
# Description: fsutil.exe — Windows filesystem management: file info, disk info,
#   volume info, hard links, sparse files, file system statistics, quota management,
#   and USN journal queries
# Source: Built-in Windows tool at C:\Windows\system32\fsutil.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows filesystem utility — query file info, disk geometry, volume info, NTFS file system, hard links, sparse files, file system statistics, disk quotas, and USN journal",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/fsutil",
    "added": "2026-07-17",
    "command": "fsutil <fsinfo|file|volume|behavior|dirty|quota|repair|sparse|usn|hardlink|reparsepoint>",
}

ALLOWED_SUBCOMMANDS = {
    "fsinfo": ["drives", "drivetype", "volumeinfo", "ntfsinfo", "statistics"],
    "file": ["queryfilenamebydata", "queryfilemetadata", "validdata", "layout", "optimizemedia", "querynamebydatalocation"],
    "volume": ["allocationreport", "diskfree", "dismount", "fsinfo", "health", "querycluster", "repair"],
    "hardlink": ["create", "list"],
    "sparse": ["queryflag", "queryrange", "setflag", "setrange"],
    "usn": ["createmft", "deletejournal", "enumdata", "queryjournal", "readjournal", "readdata"],
    "quota": ["modify", "query", "track", "violations"],
    "behavior": ["query", "set", "queryallowextents", "querydisable8dot3", "querydisablecompression", "querydisablelastaccess", "queryencryptpagingfile", "querymftzone", "querymemorypriority", "queryquotanotify", "queryresolvebitmap", "querysymlinkevaluation"],
    "dirty": ["query", "set"],
    "reparsepoint": ["query", "delete"],
}


def _find_fsutil():
    exe = shutil.which("fsutil") or shutil.which("fsutil.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\fsutil.exe",
        r"C:\Windows\SysWOW64\fsutil.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_fsutil_available():
    exe = _find_fsutil()
    if not exe:
        return False
    try:
        result = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return result.returncode in (0, 1)
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_fsutil(args, timeout=15):
    exe = _find_fsutil()
    if not exe:
        raise RuntimeError("fsutil not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def register_routes(app, state, require_auth):
    _log("register_routes: fsutil")

    @app.route("/auto/fsutil/info", methods=["GET"])
    @require_auth
    def route_auto_fsutil_info():
        return jsonify({
            "ok": True,
            "feature": "fsutil",
            "info": FEATURE_INFO,
            "available": _is_fsutil_available(),
        })

    @app.route("/auto/fsutil/ping", methods=["GET"])
    @require_auth
    def route_auto_fsutil_ping():
        available = _is_fsutil_available()
        return jsonify({
            "ok": available,
            "feature": "fsutil",
            "available": available,
        })

    @app.route("/auto/fsutil/fsinfo", methods=["POST"])
    @require_auth
    def route_auto_fsutil_fsinfo():
        """Query filesystem information: drives, drivetype, volumeinfo, ntfsinfo, statistics."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        subcommand = body.get("subcommand", "").strip().lower()
        if not subcommand:
            return _missing_field("subcommand")
        if subcommand not in ALLOWED_SUBCOMMANDS["fsinfo"]:
            return jsonify({"ok": False, "error": f"invalid fsinfo subcommand: {subcommand}"}), 400

        args = ["fsinfo", subcommand]
        if subcommand in ("drivetype", "volumeinfo", "ntfsinfo", "statistics"):
            drive = body.get("drive", "")
            if drive:
                args.append(drive)

        try:
            stdout, stderr, rc = _run_fsutil(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "subcommand": subcommand,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "fsutil fsinfo command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/fsutil/diskfree", methods=["GET"])
    @require_auth
    def route_auto_fsutil_diskfree():
        """Query disk free space for a specific drive."""
        try:
            from flask import request
            drive = request.args.get("drive", "c:")
        except Exception:
            drive = "c:"

        drive = drive.strip().rstrip("\\/")
        if not drive.endswith(":"):
            drive = drive + ":"

        try:
            stdout, stderr, rc = _run_fsutil(["volume", "diskfree", drive], timeout=15)
            return jsonify({
                "ok": rc == 0,
                "drive": drive,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "fsutil diskfree command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/fsutil/file", methods=["POST"])
    @require_auth
    def route_auto_fsutil_file():
        """Query file metadata: layout, name, metadata info, or valid data length."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        subcommand = body.get("subcommand", "").strip().lower()
        file_path = body.get("path", "").strip()

        if not subcommand:
            return _missing_field("subcommand")
        if subcommand not in ALLOWED_SUBCOMMANDS["file"]:
            return jsonify({"ok": False, "error": f"invalid file subcommand: {subcommand}"}), 400
        if not file_path:
            return _missing_field("path")

        args = ["file", subcommand, file_path]

        try:
            stdout, stderr, rc = _run_fsutil(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "subcommand": subcommand,
                "path": file_path,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "fsutil file command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/fsutil/volume", methods=["GET"])
    @require_auth
    def route_auto_fsutil_volume():
        """Query volume information: allocation report or health for a drive."""
        try:
            from flask import request
            drive = request.args.get("drive", "c:")
            query = request.args.get("query", "allocationreport").strip().lower()
        except Exception:
            drive = "c:"
            query = "allocationreport"

        drive = drive.strip().rstrip("\\/")
        if not drive.endswith(":"):
            drive = drive + ":"

        allowed_volume = ["allocationreport", "health"]
        for q in query.split(","):
            q = q.strip()
            if q and q not in allowed_volume:
                return jsonify({"ok": False, "error": f"invalid volume query: {q}"}), 400

        results = []
        for q in query.split(","):
            q = q.strip()
            if not q:
                continue
            try:
                stdout, stderr, rc = _run_fsutil(["volume", q, drive], timeout=15)
                results.append({
                    "query": q,
                    "ok": rc == 0,
                    "stdout": stdout.strip(),
                    "stderr": stderr.strip(),
                })
            except subprocess.TimeoutExpired:
                results.append({"query": q, "ok": False, "error": "timed out"})
            except Exception as e:
                results.append({"query": q, "ok": False, "error": str(e)})

        return jsonify({"ok": True, "drive": drive, "results": results})

    @app.route("/auto/fsutil/hardlink", methods=["POST"])
    @require_auth
    def route_auto_fsutil_hardlink():
        """Create or list hard links."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        subcommand = body.get("subcommand", "").strip().lower()
        if subcommand not in ALLOWED_SUBCOMMANDS["hardlink"]:
            return jsonify({"ok": False, "error": f"invalid hardlink subcommand: {subcommand}"}), 400

        if subcommand == "create":
            filename = body.get("filename", "").strip()
            newpath = body.get("newpath", "").strip()
            if not filename:
                return _missing_field("filename")
            if not newpath:
                return _missing_field("newpath")
            args = ["hardlink", "create", newpath, filename]
        else:  # list
            filename = body.get("filename", "").strip()
            if not filename:
                return _missing_field("filename")
            args = ["hardlink", "list", filename]

        try:
            stdout, stderr, rc = _run_fsutil(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "subcommand": subcommand,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "fsutil hardlink command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/fsutil/quota", methods=["POST"])
    @require_auth
    def route_auto_fsutil_quota():
        """Query or manage disk quotas on a volume."""
        try:
            body = _json_body()
        except Exception:
            return jsonify({"ok": False, "error": "invalid JSON body"}), 400

        subcommand = body.get("subcommand", "").strip().lower()
        if subcommand not in ALLOWED_SUBCOMMANDS["quota"]:
            return jsonify({"ok": False, "error": f"invalid quota subcommand: {subcommand}"}), 400

        drive = body.get("drive", "c:").strip()
        if not drive.endswith(":"):
            drive = drive + ":"

        args = ["quota", subcommand, drive]
        if subcommand == "modify":
            threshold = body.get("threshold", "")
            limit = body.get("limit", "")
            if threshold:
                args.extend(["/threshold", str(threshold)])
            if limit:
                args.extend(["/limit", str(limit)])

        try:
            stdout, stderr, rc = _run_fsutil(args, timeout=15)
            return jsonify({
                "ok": rc == 0,
                "subcommand": subcommand,
                "drive": drive,
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "fsutil quota command timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
