# Auto-added feature: microsoft/windows (built-in) — bitsadmin
# Description: bitsadmin.exe — BITS (Background Intelligent Transfer Service) administration CLI.
#   Manage background file download/upload jobs: create, list, monitor, suspend, resume,
#   cancel, and complete BITS transfer jobs. Add files to jobs, set job priority,
#   display job progress and error info. Manage BITS cache and peer caching settings.
# Source: Built-in Windows tool at C:\Windows\system32\bitsadmin.exe

import os
import shutil
import subprocess

from flask import jsonify
from shared import _json_body, _missing_field

FEATURE_INFO = {
    "repo": "microsoft/windows",
    "stars": 0,
    "desc": "Built-in Windows BITS (Background Intelligent Transfer Service) administration — create and manage background download/upload jobs, list all jobs with status/progress, monitor transfer activity, suspend/resume/cancel/complete jobs, add files to jobs, set job priority, manage BITS cache and peer caching",
    "url": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/bitsadmin",
    "added": "2026-07-18",
    "command": "bitsadmin /<operation> [args]",
}

JOB_STATE_MAP = {
    "QUEUED": "queued",
    "CONNECTING": "connecting",
    "TRANSFERRING": "transferring",
    "SUSPENDED": "suspended",
    "ERROR": "error",
    "TRANSIENT_ERROR": "transient_error",
    "TRANSFERRED": "transferred",
    "ACKNOWLEDGED": "acknowledged",
    "CANCELLED": "cancelled",
}

JOB_TYPE_MAP = {
    "DOWNLOAD": "download",
    "UPLOAD": "upload",
    "UPLOAD-REPLY": "upload_reply",
}


def _find_bitsadmin():
    """Locate bitsadmin.exe."""
    exe = shutil.which("bitsadmin") or shutil.which("bitsadmin.exe")
    if exe:
        return exe
    for p in [
        r"C:\Windows\system32\bitsadmin.exe",
        r"C:\Windows\SysWOW64\bitsadmin.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _is_bitsadmin_available():
    """Check bitsadmin responds."""
    exe = _find_bitsadmin()
    if not exe:
        return False
    try:
        result = subprocess.run(
            [exe, "/LIST"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_bitsadmin(args, timeout=30):
    """Run bitsadmin.exe with given args, return output or raise."""
    exe = _find_bitsadmin()
    if not exe:
        raise RuntimeError("bitsadmin.exe not found on system")
    # Use /RAWRETURN to get machine-parseable output where possible
    full_args = ["/RAWRETURN"] + args
    try:
        result = subprocess.run(
            [exe] + full_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("bitsadmin operation timed out")
    except OSError as e:
        raise RuntimeError(f"bitsadmin execution failed: {e}")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "bitsadmin returned non-zero exit code")
    return result.stdout


def _parse_job_line(line):
    """Parse a single line from bitsadmin /LIST /VERBOSE output."""
    result = {}
    line = line.strip()
    # Try to match "{GUID}" job format
    if line.startswith("{"):
        parts = line.split("}", 1)
        if len(parts) >= 2:
            result["job_id"] = parts[0] + "}"
            rest = parts[1].strip()
            # Try to extract type
            for t, tname in JOB_TYPE_MAP.items():
                if rest.startswith(t):
                    result["type"] = tname
                    rest = rest[len(t):].strip()
                    break
            # The rest is the job name
            if rest and not rest.startswith("{"):
                result["display_name"] = rest
    return result


def _parse_job_info(output):
    """Parse INFO output into structured dict."""
    info = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        parts = stripped.split(":", 1)
        key = parts[0].strip()
        val = parts[1].strip()
        info[key] = val
    return info


def _parse_job_state(state_str):
    """Normalize job state string."""
    s = state_str.strip().upper()
    return JOB_STATE_MAP.get(s, s.lower())


def register_routes(app, state, require_auth):
    @app.route("/auto/bitsadmin/info", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/bitsadmin/ping", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_ping():
        try:
            available = _is_bitsadmin_available()
            return jsonify({
                "status": "ok" if available else "unavailable",
                "feature": "bitsadmin (built-in)",
                "available": available,
            })
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    @app.route("/auto/bitsadmin/jobs", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_jobs():
        """List all BITS transfer jobs."""
        try:
            output = _run_bitsadmin(["/LIST", "/VERBOSE"], timeout=15)
            jobs = []
            current_job = {}
            for line in output.splitlines():
                stripped = line.strip()
                if not stripped:
                    if current_job:
                        jobs.append(current_job)
                        current_job = {}
                    continue
                parsed = _parse_job_line(stripped)
                if parsed:
                    if current_job:
                        jobs.append(current_job)
                    current_job = parsed
                    continue
                if ":" in stripped:
                    parts = stripped.split(":", 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if key and val:
                        current_job[key] = val
            if current_job:
                jobs.append(current_job)
            return jsonify({
                "ok": True,
                "jobs": jobs,
                "count": len(jobs),
                "raw": output,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/info", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_info():
        """Get detailed info about a specific BITS job by name or GUID."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/INFO", job_id, "/VERBOSE"], timeout=15)
            info = _parse_job_info(output)
            # Extract job state from info
            if "State" in info:
                info["state"] = _parse_job_state(info["State"])
            return jsonify({"ok": True, "job_id": job_id, "info": info, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/create", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_create():
        """Create a new BITS transfer job."""
        body = _json_body()
        name = (body.get("name") or "").strip()
        if not name:
            return _missing_field("name")
        job_type = (body.get("type") or "download").strip().lower()
        if job_type not in ("download", "upload", "upload_reply"):
            return jsonify({"ok": False, "error": f"Invalid type '{job_type}'. Must be 'download', 'upload', or 'upload_reply'"}), 400
        type_flag = f"/{job_type.upper().replace('_', '-')}"
        try:
            output = _run_bitsadmin(["/CREATE", type_flag, name], timeout=15)
            return jsonify({"ok": True, "name": name, "type": job_type, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/add_file", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_add_file():
        """Add a file to an existing BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        remote_url = (body.get("remote_url") or "").strip()
        if not remote_url:
            return _missing_field("remote_url")
        local_path = (body.get("local_path") or "").strip()
        if not local_path:
            return _missing_field("local_path")
        try:
            output = _run_bitsadmin(["/ADDFILE", job_id, remote_url, local_path], timeout=15)
            return jsonify({
                "ok": True,
                "job_id": job_id,
                "remote_url": remote_url,
                "local_path": local_path,
                "output": output,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/resume", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_resume():
        """Resume a suspended BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/RESUME", job_id], timeout=15)
            return jsonify({"ok": True, "job_id": job_id, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/suspend", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_suspend():
        """Suspend an active BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/SUSPEND", job_id], timeout=15)
            return jsonify({"ok": True, "job_id": job_id, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/cancel", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_cancel():
        """Cancel a BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/CANCEL", job_id], timeout=15)
            return jsonify({"ok": True, "job_id": job_id, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/complete", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_complete():
        """Complete a transferred BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/COMPLETE", job_id], timeout=15)
            return jsonify({"ok": True, "job_id": job_id, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/job/files", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_job_files():
        """List files in a BITS job."""
        body = _json_body()
        job_id = (body.get("job_id") or "").strip()
        if not job_id:
            return _missing_field("job_id")
        try:
            output = _run_bitsadmin(["/LISTFILES", job_id], timeout=15)
            return jsonify({"ok": True, "job_id": job_id, "output": output, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/monitor", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_monitor():
        """Monitor the BITS transfer manager."""
        try:
            output = _run_bitsadmin(["/MONITOR"], timeout=10)
            return jsonify({"ok": True, "output": output, "raw": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/reset", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_reset():
        """Delete all jobs in the BITS transfer manager."""
        try:
            output = _run_bitsadmin(["/RESET", "/ALLUSERS"], timeout=30)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/cache/info", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_cache_info():
        """Get BITS cache information."""
        try:
            output = _run_bitsadmin(["/CACHE", "/INFO"], timeout=10)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/cache/delete", methods=["POST"])
    @require_auth
    def route_auto_bitsadmin_cache_delete():
        """Delete items from BITS cache."""
        body = _json_body()
        record_id = (body.get("record_id") or "").strip()
        try:
            args = ["/CACHE", "/DELETE"]
            if record_id:
                args.append(f"/RecordID={record_id}")
            output = _run_bitsadmin(args, timeout=15)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/auto/bitsadmin/peers/list", methods=["GET"])
    @require_auth
    def route_auto_bitsadmin_peers_list():
        """List BITS peers."""
        try:
            output = _run_bitsadmin(["/PEERS", "/LIST"], timeout=10)
            return jsonify({"ok": True, "output": output})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 503
