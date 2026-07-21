# Auto-added feature: microsoft/windows (built-in) — DriverQuery
# Description: driverquery.exe — Windows installed driver listing CLI.
#   Enumerate all installed device/system drivers, filter by format
#   (TABLE/LIST/CSV), show signed driver info, verbose details,
#   query remote systems.
# Source: Built-in Windows tool at C:\Windows\system32\driverquery.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows driver listing — enumerate all installed device/system drivers, display as TABLE/LIST/CSV, show signed driver info, verbose module details, query remote systems",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/driverquery",
    "added": "2026-07-21",
    "command": "driverquery [/FO TABLE|LIST|CSV] [/NH] [/SI] [/V] [/S system]",
}


def _find_driverquery():
    """Locate driverquery.exe — always in system32 on Windows."""
    exe = shutil.which("driverquery") or shutil.which("driverquery.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\driverquery.exe",
        r"C:\Windows\SysWOW64\driverquery.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_driverquery_available():
    exe = _find_driverquery()
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "/?"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_driverquery(args, timeout=15):
    """Run driverquery with given args, return (stdout, stderr, exit_code)."""
    exe = _find_driverquery()
    if not exe:
        raise RuntimeError("driverquery not found")
    result = subprocess.run(
        [exe] + args, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout, result.stderr, result.returncode


def _parse_csv_drivers(text):
    """Parse driverquery CSV output into list of dicts."""
    lines = text.strip().splitlines()
    if not lines:
        return []
    # First line is header
    headers = [h.strip().strip('"') for h in lines[0].split(",")]
    drivers = []
    for line in lines[1:]:
        if not line.strip():
            continue
        # Simple CSV parse (driverquery CSV doesn't use embedded commas)
        values = [v.strip().strip('"') for v in line.split(",")]
        entry = {}
        for i, h in enumerate(headers):
            if i < len(values):
                entry[h] = values[i]
            else:
                entry[h] = ""
        drivers.append(entry)
    return drivers


def register_routes(app, state, require_auth):
    @app.route("/auto/driverquery/info", methods=["GET"])
    @require_auth
    def route_auto_driverquery_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/driverquery/ping", methods=["GET"])
    @require_auth
    def route_auto_driverquery_ping():
        exe = _find_driverquery()
        available = _is_driverquery_available() if exe else False
        return jsonify({
            "status": "ok",
            "feature": "driverquery (built-in)",
            "available": available,
            "command": exe or "driverquery",
        })

    @app.route("/auto/driverquery/list", methods=["GET"])
    @require_auth
    def route_auto_driverquery_list():
        """List drivers as structured JSON (parsed from CSV output).
        
        Query params:
          signed (optional, bool): Only show signed driver info
          verbose (optional, bool): Show verbose module details
        """
        from flask import request

        args = ["/FO", "CSV"]

        show_signed = request.args.get("signed", "").lower() in ("1", "true", "yes")
        verbose = request.args.get("verbose", "").lower() in ("1", "true", "yes")

        if show_signed:
            args.append("/SI")
        if verbose:
            args.append("/V")

        try:
            stdout, stderr, rc = _run_driverquery(args)
            if rc != 0:
                return jsonify({"ok": False, "error": stderr.strip() or "driverquery failed"}), 502
            drivers = _parse_csv_drivers(stdout)
            return jsonify({
                "ok": True,
                "drivers": drivers,
                "count": len(drivers),
                "signed_only": show_signed,
                "verbose": verbose,
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "driverquery timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/driverquery/raw", methods=["GET"])
    @require_auth
    def route_auto_driverquery_raw():
        """List drivers as raw text table.
        
        Query params:
          format (optional, str): 'TABLE' (default), 'LIST', or 'CSV'
          no_header (optional, bool): Omit column headers (TABLE/CSV only)
          signed (optional, bool): Only show signed driver info
          verbose (optional, bool): Show verbose module details
        """
        from flask import request

        fmt = request.args.get("format", "TABLE").upper()
        if fmt not in ("TABLE", "LIST", "CSV"):
            return jsonify({"ok": False, "error": f"invalid format '{fmt}'. Use TABLE, LIST, or CSV"}), 400

        args = ["/FO", fmt]

        no_header = request.args.get("no_header", "").lower() in ("1", "true", "yes")
        if no_header and fmt in ("TABLE", "CSV"):
            args.append("/NH")

        show_signed = request.args.get("signed", "").lower() in ("1", "true", "yes")
        verbose = request.args.get("verbose", "").lower() in ("1", "true", "yes")

        if show_signed:
            args.append("/SI")
        if verbose:
            args.append("/V")

        try:
            stdout, stderr, rc = _run_driverquery(args)
            return jsonify({
                "ok": True,
                "exit_code": rc,
                "format": fmt,
                "output": stdout.strip() if rc == 0 else stderr.strip(),
            })
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "driverquery timed out"}), 504
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
