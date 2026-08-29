"""Long-running task supervisor routes.

Endpoints:
  POST /supervise/start        - spawn a command and babysit it end-to-end
  GET  /supervise/list         - list all supervised jobs (active + finished)
  GET  /supervise/status/<id>  - live status, matched patterns, retry count
  POST /supervise/stop         - stop a running job

A supervised job runs a command, captures stdout/stderr on a rolling buffer,
asserts against expected/error output patterns, detects hangs (no output for
N seconds), and auto-retries with exponential backoff up to a cap. Optional
on_success/on_failure webhooks fire on completion. This turns "babysit a long
task, re-run it when it hangs, grep the log, then act" into a fire-and-forget
goal. Standard-library only, so it works on Windows and stays CI-green on Linux.
"""

import json
import re
import shlex
import subprocess
import threading
import time
import urllib.request
import uuid

from flask import jsonify

from shared import _json_body, _log, _missing_field


_JOBS = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 64
_MAX_TAIL_LINES = 500
_CLEANUP_AGE_SEC = 6 * 3600  # drop finished job records after 6 hours


def _parse_command(data):
    command = data.get("command")
    if isinstance(command, list):
        args = [str(p) for p in command if str(p)]
    elif isinstance(command, str) and command.strip():
        args = shlex.split(command, posix=False)
    else:
        exe = data.get("path") or data.get("exe")
        if not exe:
            raise ValueError("missing command")
        extra = data.get("args", [])
        if isinstance(extra, str):
            extra_args = shlex.split(extra, posix=False)
        elif isinstance(extra, list):
            extra_args = [str(p) for p in extra]
        else:
            extra_args = []
        args = [str(exe)] + extra_args
    if not args:
        raise ValueError("command is empty")
    return args


def _compile_patterns(raw):
    """Normalize a pattern list (string or list) into compiled regexes."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        if item is None:
            continue
        try:
            out.append(re.compile(str(item)))
        except re.error as exc:
            raise ValueError(f"invalid regex pattern '{item}': {exc}")
    return out


def _post_webhook(url, payload):
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except Exception as exc:
        _log(f"supervise: webhook {url} failed: {exc}")
        return None


def _kill(proc):
    try:
        proc.kill()
    except Exception:
        pass


def _run_job(job):
    attempt = 0
    backoff = float(job.get("backoff_sec") or 0)
    hang_timeout = job.get("hang_timeout_sec")
    max_retries = int(job.get("max_retries") or 0)
    expected = job["expected_patterns"]
    errors = job["error_patterns"]

    while True:
        attempt += 1
        job["attempt"] = attempt
        job["state"] = "running"
        job["last_output_time"] = time.time()
        job["tail"] = []
        job["matched_expected"] = []
        job["matched_errors"] = []

        try:
            proc = subprocess.Popen(
                job["args"],
                cwd=job.get("cwd") or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            job["state"] = "failed"
            job["error"] = f"spawn failed: {exc}"
            job["exit_code"] = None
            job["finished_at"] = time.time()
            _notify(job)
            return
        job["proc"] = proc
        job["pid"] = proc.pid

        def _reader():
            try:
                for line in proc.stdout:
                    if job["_stop"].is_set():
                        break
                    line = line.rstrip("\r\n")
                    _ingest(job, line, expected, errors)
            except Exception:
                pass

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        hang_hit = False
        error_hit = False
        while True:
            if job["_stop"].is_set():
                _kill(proc)
                job["state"] = "stopped"
                job["stop_reason"] = "user"
                job["finished_at"] = time.time()
                return
            rc = proc.poll()
            if rc is not None:
                reader.join(timeout=1.0)
                break
            if hang_timeout and (time.time() - job["last_output_time"]) >= hang_timeout:
                hang_hit = True
                job["hang_count"] = int(job.get("hang_count", 0)) + 1
                _kill(proc)
                reader.join(timeout=1.0)
                break
            if job["error_hit"]:
                error_hit = True
                job["error_count"] = int(job.get("error_count", 0)) + 1
                _kill(proc)
                reader.join(timeout=1.0)
                break
            time.sleep(0.4)

        if job["_stop"].is_set():
            return

        job["exit_code"] = proc.poll()

        # Determine retry vs. terminal outcome.
        retryable = hang_hit or error_hit
        if retryable and attempt <= max_retries:
            job["state"] = "retrying"
            job["retry_count"] = attempt
            _log(f"supervise {job['id']}: {('hang' if hang_hit else 'error-pattern')} "
                 f"attempt {attempt}, retrying in {backoff}s")
            time.sleep(backoff)
            backoff = backoff * 2 if backoff else backoff
            continue

        # Terminal.
        if hang_hit:
            job["state"] = "failed"
            job["error"] = "hang detected (no output)"
        elif error_hit:
            job["state"] = "failed"
            job["error"] = "error pattern matched"
        elif expected and not _all_expected_matched(job, expected):
            job["state"] = "failed"
            job["error"] = "expected patterns not all matched"
        elif job["exit_code"] != 0:
            job["state"] = "failed"
            job["error"] = f"non-zero exit code {job['exit_code']}"
        else:
            job["state"] = "success"
        job["finished_at"] = time.time()
        _notify(job)
        return


def _ingest(job, line, expected, errors):
    job["last_output_time"] = time.time()
    job["tail"].append(line)
    if len(job["tail"]) > _MAX_TAIL_LINES:
        job["tail"] = job["tail"][-_MAX_TAIL_LINES:]
    for pat in expected:
        if pat.search(line):
            job["matched_expected"].append(line)
    for pat in errors:
        if pat.search(line):
            job["matched_errors"].append(line)
            job["error_hit"] = True


def _all_expected_matched(job, expected):
    joined = "\n".join(job["tail"])
    for pat in expected:
        if not pat.search(joined):
            return False
    return True


def _notify(job):
    state = job["state"]
    payload = {
        "id": job["id"],
        "command": job["command"],
        "state": state,
        "attempt": job["attempt"],
        "exit_code": job.get("exit_code"),
        "retry_count": job.get("retry_count", 0),
        "hang_count": job.get("hang_count", 0),
        "error_count": job.get("error_count", 0),
        "tail": job["tail"][-50:],
    }
    url = job.get("on_success") if state == "success" else job.get("on_failure")
    if url:
        _post_webhook(url, payload)
    _log(f"supervise {job['id']}: {state} (attempt {job['attempt']})")


def _cleanup_locked():
    now = time.time()
    stale = [k for k, j in _JOBS.items()
             if j.get("finished_at") and now - j["finished_at"] > _CLEANUP_AGE_SEC]
    for k in stale:
        _JOBS.pop(k, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/supervise/start", methods=["POST"])
    @require_auth
    def route_supervise_start():
        d = _json_body()
        if not isinstance(d, dict):
            d = {}

        try:
            args = _parse_command(d)
            expected = _compile_patterns(d.get("expected_patterns"))
            errors = _compile_patterns(d.get("error_patterns"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        max_retries = d.get("max_retries", 0)
        try:
            max_retries = int(max_retries)
        except (TypeError, ValueError):
            return jsonify({"error": "max_retries must be an integer"}), 400
        if max_retries < 0 or max_retries > 10:
            return jsonify({"error": "max_retries must be 0-10"}), 400

        hang_timeout = d.get("hang_timeout_sec")
        if hang_timeout is not None:
            try:
                hang_timeout = float(hang_timeout)
            except (TypeError, ValueError):
                return jsonify({"error": "hang_timeout_sec must be a number"}), 400
            if hang_timeout <= 0:
                hang_timeout = None

        backoff = d.get("backoff_sec", 5)
        try:
            backoff = float(backoff)
        except (TypeError, ValueError):
            backoff = 5.0

        raw_cmd = d.get("command")
        if isinstance(raw_cmd, list):
            command_display = " ".join(str(p) for p in raw_cmd)
        elif isinstance(raw_cmd, str) and raw_cmd.strip():
            command_display = raw_cmd
        else:
            command_display = " ".join(args)

        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "command": command_display,
            "args": args,
            "cwd": d.get("cwd") or None,
            "expected_patterns": expected,
            "error_patterns": errors,
            "hang_timeout_sec": hang_timeout,
            "max_retries": max_retries,
            "backoff_sec": backoff,
            "on_success": d.get("on_success"),
            "on_failure": d.get("on_failure"),
            "state": "queued",
            "attempt": 0,
            "retry_count": 0,
            "hang_count": 0,
            "error_count": 0,
            "error_hit": False,
            "tail": [],
            "matched_expected": [],
            "matched_errors": [],
            "proc": None,
            "pid": None,
            "exit_code": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "_stop": threading.Event(),
        }

        with _JOBS_LOCK:
            _cleanup_locked()
            if len(_JOBS) >= _MAX_JOBS:
                return jsonify({"error": f"max {_MAX_JOBS} supervised jobs"}), 429
            _JOBS[job_id] = job

        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        _log(f"supervise/start id={job_id} cmd={job['command'][:80]}")
        return jsonify({"status": "ok", "id": job_id, "command": job["command"]})

    @app.route("/supervise/list", methods=["GET"])
    @require_auth
    def route_supervise_list():
        with _JOBS_LOCK:
            jobs = [{
                "id": j["id"],
                "command": j["command"],
                "state": j["state"],
                "attempt": j["attempt"],
                "retry_count": j.get("retry_count", 0),
                "pid": j.get("pid"),
                "exit_code": j.get("exit_code"),
                "started_at": j["started_at"],
                "finished_at": j.get("finished_at"),
            } for j in _JOBS.values()]
        jobs.sort(key=lambda j: j["started_at"], reverse=True)
        return jsonify({"status": "ok", "count": len(jobs), "jobs": jobs})

    @app.route("/supervise/status/<job_id>", methods=["GET"])
    @require_auth
    def route_supervise_status(job_id):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            return jsonify({"error": f"job '{job_id}' not found"}), 404
        return jsonify({
            "status": "ok",
            "id": job["id"],
            "command": job["command"],
            "state": job["state"],
            "attempt": job["attempt"],
            "retry_count": job.get("retry_count", 0),
            "hang_count": job.get("hang_count", 0),
            "error_count": job.get("error_count", 0),
            "pid": job.get("pid"),
            "exit_code": job.get("exit_code"),
            "error": job.get("error"),
            "matched_expected": job.get("matched_expected", [])[-20:],
            "matched_errors": job.get("matched_errors", [])[-20:],
            "started_at": job["started_at"],
            "finished_at": job.get("finished_at"),
            "tail": job["tail"][-200:],
        })

    @app.route("/supervise/stop", methods=["POST"])
    @require_auth
    def route_supervise_stop():
        d = _json_body()
        job_id = (d.get("id") or "").strip() if isinstance(d, dict) else ""
        if not job_id:
            return _missing_field("id")
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            return jsonify({"error": f"job '{job_id}' not found"}), 404
        job["_stop"].set()
        proc = job.get("proc")
        if proc is not None and proc.poll() is None:
            _kill(proc)
        _log(f"supervise/stop id={job_id}")
        return jsonify({"status": "ok", "id": job_id, "stopping": True})
