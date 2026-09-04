"""Print queue management routes.

Endpoints:
  GET/POST /print/list    - list installed printers (name, status, default, ...)
  GET/POST /print/jobs    - list queued print jobs (optionally per printer)
  POST     /print/pause   - pause a print job by printer + job id
  POST     /print/resume  - resume a paused print job
  POST     /print/cancel  - cancel/remove a print job from the queue
  POST     /print/file    - send a file to the default printer or a named one

Uses PowerShell Get-Printer / Get-PrintJob / Suspend-PrintJob / Resume-PrintJob
/ Remove-PrintJob with pure-ASCII argument strings. On non-Windows hosts the
endpoints return HTTP 501 rather than failing at import time so the Linux
syntax-check CI stays green.
"""

import json as _json
import os
import re
import shutil
import subprocess

from flask import jsonify

from shared import _json_body, _log, _missing_field


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Printer share names on Windows allow letters, digits, spaces, and a handful
# of punctuation. Disallow quotes and shell metacharacters so the value can be
# interpolated into an ASCII PowerShell script safely.
_PRINTER_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-()#+&]{1,128}$")
# Job IDs from the spooler are non-negative 32-bit integers.
_JOB_ID_RE = re.compile(r"^\d{1,10}$")


def _windows_only():
    return jsonify({"error": "Windows-only endpoint"}), 501


def _find_powershell():
    return (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    )


def _run_ps(script, timeout=20):
    """Run a PowerShell script and return (stdout, stderr, returncode)."""
    ps = _find_powershell()
    if not ps or not os.path.isfile(ps):
        return "", "powershell.exe not found", -1
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out", -1
    except FileNotFoundError as exc:
        return "", str(exc), -1


def _parse_json_output(text):
    """PowerShell ConvertTo-Json emits an object or array. Normalize to list."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = _json.loads(text)
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _normalize_printer_name(raw):
    """Return a validated printer name or None."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or not _PRINTER_NAME_RE.fullmatch(value):
        return None
    return value


def _normalize_job_id(raw):
    """Return an int job id or None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, str) and _JOB_ID_RE.fullmatch(raw.strip()):
        return int(raw.strip())
    return None


# ASCII-only PowerShell fragments.
_LIST_PRINTERS_PS = (
    "Get-Printer | "
    "Select-Object Name,PrinterStatus,Type,DriverName,PortName,Shared,"
    "Published,Location,Comment | "
    "ConvertTo-Json -Depth 3 -Compress"
)

_DEFAULT_PRINTER_PS = (
    "$d = Get-CimInstance -ClassName Win32_Printer -Filter 'Default=True' "
    "-ErrorAction SilentlyContinue | Select-Object -First 1; "
    "if ($d) { $d.Name } else { '' }"
)


def _list_jobs_ps(printer_name=None):
    if printer_name:
        # printer_name is pre-validated by _normalize_printer_name so it is
        # safe to interpolate into a single-quoted PowerShell string.
        target = f"Get-PrintJob -PrinterName '{printer_name}'"
    else:
        target = "Get-Printer | Get-PrintJob"
    return (
        f"{target} -ErrorAction SilentlyContinue | "
        "Select-Object Id,PrinterName,DocumentName,JobStatus,Position,Size,"
        "SubmittedTime,UserName,ComputerName,TotalPages,PagesPrinted | "
        "ConvertTo-Json -Depth 3 -Compress"
    )


def _job_action_ps(cmdlet, printer_name, job_id):
    return (
        "$ErrorActionPreference = 'Stop'; "
        f"{cmdlet} -PrinterName '{printer_name}' -ID {job_id}; "
        "Write-Output 'ok'"
    )


def _print_file_ps(file_path, printer_name):
    # file_path has been resolved with Path().resolve(); embed with a
    # single-quoted PS literal and escape any embedded single quotes.
    escaped_path = file_path.replace("'", "''")
    if printer_name:
        return (
            "$ErrorActionPreference = 'Stop'; "
            f"Start-Process -FilePath '{escaped_path}' -Verb PrintTo "
            f"-ArgumentList '\"{printer_name}\"' -WindowStyle Hidden; "
            "Write-Output 'submitted'"
        )
    return (
        "$ErrorActionPreference = 'Stop'; "
        f"Start-Process -FilePath '{escaped_path}' -Verb Print "
        "-WindowStyle Hidden; "
        "Write-Output 'submitted'"
    )


def register_routes(app, state, require_auth):
    ps_exe = _find_powershell()
    ps_available = bool(ps_exe and os.path.isfile(ps_exe))

    @app.route("/print/list", methods=["GET", "POST"])
    @require_auth
    def route_print_list():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        out, err, rc = _run_ps(_LIST_PRINTERS_PS, timeout=20)
        if rc != 0:
            return jsonify({
                "error": err.strip() or "Get-Printer failed",
                "returncode": rc,
            }), 500
        printers = _parse_json_output(out)

        default_name = ""
        d_out, _d_err, d_rc = _run_ps(_DEFAULT_PRINTER_PS, timeout=15)
        if d_rc == 0:
            default_name = (d_out or "").strip()

        for entry in printers:
            if isinstance(entry, dict):
                entry["Default"] = bool(
                    default_name and str(entry.get("Name") or "").casefold() == str(default_name).casefold()
                )

        return jsonify({
            "printers": printers,
            "count": len(printers),
            "default": default_name,
        })

    @app.route("/print/jobs", methods=["GET", "POST"])
    @require_auth
    def route_print_jobs():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        printer_raw = None
        if isinstance(body, dict):
            printer_raw = body.get("printer") or body.get("printer_name")

        printer_name = None
        if printer_raw is not None:
            printer_name = _normalize_printer_name(printer_raw)
            if not printer_name:
                return jsonify({"error": "invalid printer name"}), 400

        script = _list_jobs_ps(printer_name)
        out, err, rc = _run_ps(script, timeout=20)
        if rc != 0:
            return jsonify({
                "error": err.strip() or "Get-PrintJob failed",
                "returncode": rc,
            }), 500
        jobs = _parse_json_output(out)
        return jsonify({
            "jobs": jobs,
            "count": len(jobs),
            "printer": printer_name or "",
        })

    def _job_action(cmdlet, action_label):
        if os.name != "nt" or not ps_available:
            return _windows_only()
        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        printer_raw = body.get("printer") or body.get("printer_name")
        if not printer_raw:
            return _missing_field("printer")
        printer_name = _normalize_printer_name(printer_raw)
        if not printer_name:
            return jsonify({"error": "invalid printer name"}), 400

        job_raw = body.get("id")
        if job_raw is None:
            job_raw = body.get("job_id")
        if job_raw is None or job_raw == "":
            return _missing_field("id")
        job_id = _normalize_job_id(job_raw)
        if job_id is None:
            return jsonify({"error": "invalid job id"}), 400

        script = _job_action_ps(cmdlet, printer_name, job_id)
        out, err, rc = _run_ps(script, timeout=20)
        ok = rc == 0 and "ok" in (out or "").lower()
        _log(f"print/{action_label} printer={printer_name} id={job_id} rc={rc}")
        return jsonify({
            "status": "ok" if ok else "error",
            "action": action_label,
            "printer": printer_name,
            "id": job_id,
            "stdout": (out or "").strip(),
            "stderr": (err or "").strip(),
            "returncode": rc,
        }), (200 if ok else 500)

    @app.route("/print/pause", methods=["POST"])
    @require_auth
    def route_print_pause():
        return _job_action("Suspend-PrintJob", "pause")

    @app.route("/print/resume", methods=["POST"])
    @require_auth
    def route_print_resume():
        return _job_action("Resume-PrintJob", "resume")

    @app.route("/print/cancel", methods=["POST"])
    @require_auth
    def route_print_cancel():
        return _job_action("Remove-PrintJob", "cancel")

    @app.route("/print/file", methods=["POST"])
    @require_auth
    def route_print_file():
        if os.name != "nt" or not ps_available:
            return _windows_only()

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        raw_path = body.get("path") or body.get("file")
        if not raw_path:
            return _missing_field("path")
        if not isinstance(raw_path, str):
            return jsonify({"error": "path must be a string"}), 400

        try:
            resolved = os.path.abspath(os.path.expanduser(raw_path))
        except (OSError, ValueError) as exc:
            return jsonify({"error": f"invalid path: {exc}"}), 400
        if not os.path.isfile(resolved):
            return jsonify({"error": "file not found", "path": resolved}), 404

        printer_raw = body.get("printer") or body.get("printer_name")
        printer_name = None
        if printer_raw:
            printer_name = _normalize_printer_name(printer_raw)
            if not printer_name:
                return jsonify({"error": "invalid printer name"}), 400

        script = _print_file_ps(resolved, printer_name)
        out, err, rc = _run_ps(script, timeout=25)
        ok = rc == 0 and "submitted" in (out or "").lower()
        _log(f"print/file path={resolved} printer={printer_name or ''} rc={rc}")
        return jsonify({
            "status": "ok" if ok else "error",
            "path": resolved,
            "printer": printer_name or "",
            "stdout": (out or "").strip(),
            "stderr": (err or "").strip(),
            "returncode": rc,
        }), (200 if ok else 500)
