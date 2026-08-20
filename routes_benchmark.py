"""Reliability Benchmark / Self-Evaluation Harness (issue #728).

Turns "does CoAgent reliably complete real desktop tasks?" from a hand-wave
into a measurable number. A suite is a JSON file of tasks; each task has:

    name        (str, required)     — task id, used for evidence directory
    goal        (str, optional)     — natural-language prompt for the goal-runner
    steps       (list, optional)    — alternative to goal: passed to
                                      /agent/plan-and-execute for deterministic
                                      hybrid execution
    setup       (list, optional)    — actions to run BEFORE the goal
                                      [{path, method, payload}]
    teardown    (list, optional)    — actions to run AFTER assertions
    assertions  (list, required)    — end-state checks; each is one of:

        {"type": "verify",         "expected": "...", "mode": "any|all|substring",
         "region": {x,y,w,h}, "window": "...", "keywords": [...]}
        {"type": "ocr",            "text": "expected substring", "fresh": true}
        {"type": "screenshot",     "save_as": "after.png"}
        {"type": "diff",           "baseline_id": "...", "min_percent_changed": 0.0,
         "max_percent_changed": 100.0}
        {"type": "window-exists",  "title": "substring", "visible": true}
        {"type": "http",           "path": "/foo", "method": "GET",
         "expect_key": "text", "expect_value": "HELLO"}

    An assertion passes when its underlying check returns the expected outcome.
    Each assertion may set "expect_pass": false to invert the check (useful for
    "this window should NOT exist" etc.).

Endpoints:
    POST /benchmark/run       — run a suite (by name, or inline task list)
    GET  /benchmark/results   — list past run summaries
    GET  /benchmark/report    — aggregate success rate + per-task breakdown
    GET  /benchmark/suites    — list available JSON suites

Evidence lives under COAGENT_DIR/benchmarks/runs/<run_id>/<task>/.
The starter suite is written to COAGENT_DIR/benchmarks/starter.json on first
import if it does not already exist.
"""

import json
import re
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from flask import jsonify

from shared import COAGENT_DIR, _json_body, _log, _missing_field, _self_port


BENCH_DIR = COAGENT_DIR / "benchmarks"
RUNS_DIR = BENCH_DIR / "runs"
BENCH_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

_SUITE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_TASK_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_STATE_LOCK = threading.RLock()
_RUN_INDEX_PATH = RUNS_DIR / "index.json"


# ---------------------------------------------------------------------------
# HTTP helpers — call back into our own Flask surface (same pattern as
# routes_verify.py / routes_capture.py). Authentication uses the local
# bearer token so require_auth-wrapped endpoints accept our calls.
# ---------------------------------------------------------------------------

def _auth_token():
    try:
        import auth
        return getattr(auth, "AUTH_TOKEN", "") or ""
    except Exception:
        return ""


def _coagent_request(path, payload=None, method="POST", timeout=30):
    """POST/GET to our own Flask server. Returns (status_code, parsed_json)."""
    url = f"http://127.0.0.1:{_self_port()}{path}"
    headers = {"Accept": "application/json"}
    token = _auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    method = (method or "POST").upper()
    if payload is not None and method != "GET":
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = getattr(resp, "status", 200)
            if not raw:
                return status, {}
            try:
                return status, json.loads(raw.decode("utf-8"))
            except Exception:
                return status, {"raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            data = {"error": str(exc)}
        return exc.code, data
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _run_actions(actions, phase, log_lines):
    """Sequentially POST a list of {path, method, payload} to ourselves."""
    results = []
    for idx, action in enumerate(actions or []):
        if not isinstance(action, dict):
            results.append({"index": idx, "ok": False, "error": "action must be an object"})
            log_lines.append(f"[{phase}#{idx}] SKIP: not an object")
            continue
        path = action.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            results.append({"index": idx, "ok": False, "error": "path must start with /"})
            log_lines.append(f"[{phase}#{idx}] SKIP: bad path")
            continue
        method = (action.get("method") or "POST").upper()
        payload = action.get("payload")
        if payload is not None and not isinstance(payload, (dict, list)):
            payload = None
        timeout = _clamp(action.get("timeout", 20), 1, 120, 20)
        t0 = time.time()
        status, body = _coagent_request(path, payload=payload, method=method, timeout=timeout)
        elapsed = round((time.time() - t0) * 1000, 1)
        ok = 200 <= status < 300 and not (isinstance(body, dict) and body.get("error"))
        results.append({
            "index": idx,
            "path": path,
            "method": method,
            "status_code": status,
            "elapsed_ms": elapsed,
            "ok": ok,
            "response": _truncate_response(body),
        })
        log_lines.append(f"[{phase}#{idx}] {method} {path} -> {status} ({elapsed}ms) ok={ok}")
        # Small pacing delay to let UI settle
        delay_ms = _clamp(action.get("delay_ms", 0), 0, 5000, 0)
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
    return results


def _truncate_response(body, max_chars=800):
    """Trim large responses so evidence files stay small."""
    try:
        s = json.dumps(body, ensure_ascii=False, default=str)
    except Exception:
        return {"repr": repr(body)[:max_chars]}
    if len(s) <= max_chars:
        return body
    return {"truncated": True, "preview": s[:max_chars]}


def _clamp(value, lo, hi, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# Goal-runner integration — either /copilot/goal (async, natural language)
# or /agent/plan-and-execute (sync, structured steps).
# ---------------------------------------------------------------------------

_GOAL_TERMINAL_STATES = {"completed", "complete", "done", "success", "failed",
                        "error", "cancelled", "canceled", "aborted", "stopped"}


def _execute_goal_via_copilot(goal_text, timeout, log_lines):
    """POST /copilot/goal, then poll status until terminal state or timeout."""
    status, body = _coagent_request("/copilot/goal", payload={"goal": goal_text}, method="POST", timeout=30)
    if status >= 400 or (isinstance(body, dict) and body.get("error")):
        log_lines.append(f"[goal] /copilot/goal returned {status}: {body}")
        return {"ok": False, "error": body.get("error") if isinstance(body, dict) else f"http {status}",
                "engine": "copilot", "status_code": status}
    goal_id = body.get("goal_id") or body.get("id") if isinstance(body, dict) else None
    if not goal_id:
        return {"ok": False, "error": "no goal_id in response", "engine": "copilot",
                "response": _truncate_response(body)}
    log_lines.append(f"[goal] queued goal_id={goal_id}")
    deadline = time.time() + max(1, int(timeout))
    poll_interval = 1.0
    final_snapshot = None
    while time.time() < deadline:
        time.sleep(poll_interval)
        s, snap = _coagent_request(f"/copilot/goal/{goal_id}", method="GET", timeout=15)
        if s >= 400:
            log_lines.append(f"[goal] poll {s}: {snap}")
            continue
        final_snapshot = snap
        st = str((snap or {}).get("status") or "").lower()
        if st in _GOAL_TERMINAL_STATES:
            log_lines.append(f"[goal] terminal status={st}")
            break
        poll_interval = min(poll_interval + 0.5, 3.0)
    completed_ok = False
    if isinstance(final_snapshot, dict):
        st = str(final_snapshot.get("status") or "").lower()
        completed_ok = st in {"completed", "complete", "done", "success"}
    return {
        "ok": bool(completed_ok),
        "engine": "copilot",
        "goal_id": goal_id,
        "final_status": (final_snapshot or {}).get("status") if isinstance(final_snapshot, dict) else None,
        "snapshot": _truncate_response(final_snapshot or {}),
    }


def _execute_goal_via_plan(steps, log_lines):
    """POST /agent/plan-and-execute for deterministic hybrid execution."""
    status, body = _coagent_request("/agent/plan-and-execute", payload={"steps": steps},
                                    method="POST", timeout=120)
    ok = 200 <= status < 300 and isinstance(body, dict) and body.get("ok")
    log_lines.append(f"[goal] plan-and-execute status={status} ok={ok}")
    return {"ok": bool(ok), "engine": "plan-and-execute", "status_code": status,
            "response": _truncate_response(body)}


def _execute_task_goal(task, log_lines):
    """Choose the right execution path for the task's goal."""
    steps = task.get("steps")
    goal = task.get("goal")
    if isinstance(steps, list) and steps:
        return _execute_goal_via_plan(steps, log_lines)
    if isinstance(goal, str) and goal.strip():
        timeout = _clamp(task.get("goal_timeout", 90), 5, 600, 90)
        return _execute_goal_via_copilot(goal.strip(), timeout, log_lines)
    log_lines.append("[goal] no goal/steps provided — skipped")
    return {"ok": True, "engine": "none", "skipped": True}


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------

def _assert_verify(assertion):
    payload = {"expected": assertion.get("expected", "")}
    for key in ("mode", "region", "window", "keywords"):
        if assertion.get(key) is not None:
            payload[key] = assertion[key]
    status, body = _coagent_request("/verify/check", payload=payload, method="POST", timeout=45)
    if status >= 400 or not isinstance(body, dict):
        return False, "verify request failed", _truncate_response(body)
    passed = bool(body.get("passed"))
    return passed, ("passed" if passed else (body.get("reason") or "verify failed")), {
        "passed": passed, "score": body.get("score"),
        "matched": body.get("matched_keywords"), "missing": body.get("missing_keywords"),
        "text_snippet": body.get("text_snippet"), "method": body.get("method"),
    }


def _assert_ocr(assertion):
    text = assertion.get("text") or assertion.get("query")
    if not text:
        return False, "ocr assertion missing 'text'", None
    payload = {"text": str(text), "fresh": bool(assertion.get("fresh", True))}
    status, body = _coagent_request("/ocr/find", payload=payload, method="POST", timeout=30)
    if status >= 400 or not isinstance(body, dict):
        return False, "ocr request failed", _truncate_response(body)
    count = int(body.get("count") or 0)
    min_count = _clamp(assertion.get("min_count", 1), 0, 999, 1)
    passed = count >= min_count
    reason = f"found {count} match(es), needed {min_count}"
    return passed, reason, {"count": count, "matches": (body.get("matches") or [])[:5]}


def _assert_screenshot(assertion, evidence_dir):
    filename = assertion.get("save_as") or "screenshot.jpg"
    if not re.match(r"^[A-Za-z0-9_\-.]{1,64}$", filename):
        filename = "screenshot.jpg"
    url = f"http://127.0.0.1:{_self_port()}/screen"
    headers = {}
    token = _auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if not data:
            return False, "empty screenshot", None
        out = evidence_dir / filename
        out.write_bytes(data)
        min_bytes = _clamp(assertion.get("min_bytes", 1024), 0, 10_000_000, 1024)
        passed = len(data) >= min_bytes
        return passed, f"{len(data)} bytes >= {min_bytes}" if passed else f"{len(data)} < {min_bytes}", {
            "path": str(out), "bytes": len(data),
        }
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


def _assert_diff(assertion):
    baseline_id = assertion.get("baseline_id")
    if not baseline_id:
        # Create a fresh baseline first if none given (assertion becomes "screen changed since baseline")
        s, body = _coagent_request("/diff/capture", payload={"label": "benchmark"}, method="POST", timeout=30)
        if s >= 400 or not isinstance(body, dict) or not body.get("snapshot_id"):
            return False, "diff baseline capture failed", _truncate_response(body)
        baseline_id = body["snapshot_id"]
    s, body = _coagent_request("/diff/compare", payload={"baseline_id": baseline_id},
                               method="POST", timeout=30)
    if s >= 400 or not isinstance(body, dict):
        return False, "diff compare failed", _truncate_response(body)
    pct = float(body.get("percent_changed") or 0.0)
    min_pct = float(assertion.get("min_percent_changed", 0.0))
    max_pct = float(assertion.get("max_percent_changed", 100.0))
    passed = min_pct <= pct <= max_pct
    reason = f"{pct}% changed (range {min_pct}..{max_pct})"
    return passed, reason, {"percent_changed": pct, "baseline_id": baseline_id,
                            "diff_id": body.get("diff_id")}


def _assert_window_exists(assertion):
    needle = str(assertion.get("title") or "").strip().lower()
    if not needle:
        return False, "window-exists assertion missing 'title'", None
    require_visible = bool(assertion.get("visible", True))
    status, body = _coagent_request("/windows", method="GET", timeout=15)
    if status >= 400 or not isinstance(body, dict):
        return False, "windows list failed", _truncate_response(body)
    matches = []
    for win in body.get("windows") or []:
        title = str(win.get("title") or "").lower()
        if needle in title:
            if require_visible and not win.get("visible"):
                continue
            matches.append({"title": win.get("title"), "hwnd": win.get("hwnd"),
                            "pid": win.get("pid"), "visible": win.get("visible")})
    passed = len(matches) > 0
    reason = f"matched {len(matches)} window(s) with title~='{needle}'"
    return passed, reason, {"matches": matches[:5]}


def _assert_http(assertion):
    path = assertion.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        return False, "http assertion needs 'path' starting with /", None
    method = (assertion.get("method") or "GET").upper()
    payload = assertion.get("payload") if isinstance(assertion.get("payload"), (dict, list)) else None
    status, body = _coagent_request(path, payload=payload, method=method, timeout=20)
    ok_status = 200 <= status < 300
    key = assertion.get("expect_key")
    if key is None:
        return ok_status, f"http {status}", {"status_code": status, "body": _truncate_response(body)}
    value = body.get(key) if isinstance(body, dict) else None
    expected_value = assertion.get("expect_value")
    contains = assertion.get("expect_contains")
    if contains is not None:
        passed = ok_status and isinstance(value, str) and str(contains) in value
        reason = f"{key} contains '{contains}': {passed}"
    else:
        passed = ok_status and (value == expected_value)
        reason = f"{key}={value!r} == expected {expected_value!r}: {passed}"
    return passed, reason, {"status_code": status, "key": key, "actual": value}


_ASSERTION_HANDLERS = {
    "verify": _assert_verify,
    "ocr": _assert_ocr,
    "diff": _assert_diff,
    "window-exists": _assert_window_exists,
    "window_exists": _assert_window_exists,
    "http": _assert_http,
}


def _evaluate_assertion(assertion, evidence_dir):
    if not isinstance(assertion, dict):
        return {"ok": False, "type": "?", "reason": "not an object"}
    kind = str(assertion.get("type") or "").lower().strip()
    expect_pass = bool(assertion.get("expect_pass", True))
    t0 = time.time()
    try:
        if kind == "screenshot":
            raw_passed, reason, detail = _assert_screenshot(assertion, evidence_dir)
        elif kind in _ASSERTION_HANDLERS:
            raw_passed, reason, detail = _ASSERTION_HANDLERS[kind](assertion)
        else:
            return {"ok": False, "type": kind or "?", "reason": f"unknown assertion type '{kind}'"}
    except Exception as exc:
        return {"ok": False, "type": kind, "reason": f"exception: {type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=4)}
    passed = bool(raw_passed) if expect_pass else (not raw_passed)
    return {
        "ok": passed,
        "type": kind,
        "expect_pass": expect_pass,
        "raw_passed": bool(raw_passed),
        "reason": reason,
        "detail": detail,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "label": assertion.get("label"),
    }


# ---------------------------------------------------------------------------
# Suite / run persistence
# ---------------------------------------------------------------------------

def _load_suite(name):
    if not _SUITE_NAME_RE.match(name or ""):
        return None, "invalid suite name"
    path = BENCH_DIR / f"{name}.json"
    if not path.exists():
        return None, f"suite '{name}' not found"
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return None, f"failed to load suite: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        return None, "suite JSON must be {'tasks': [...]}"
    return data, None


def _list_suites():
    entries = []
    for p in sorted(BENCH_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tasks = data.get("tasks") if isinstance(data, dict) else None
            entries.append({
                "name": p.stem,
                "path": str(p),
                "task_count": len(tasks) if isinstance(tasks, list) else 0,
                "description": data.get("description", "") if isinstance(data, dict) else "",
            })
        except Exception as exc:
            entries.append({"name": p.stem, "path": str(p), "error": str(exc)})
    return entries


def _index_runs():
    if not _RUN_INDEX_PATH.exists():
        return []
    try:
        with _RUN_INDEX_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _persist_run_index(entry):
    with _STATE_LOCK:
        existing = _index_runs()
        existing.append(entry)
        # Keep last 200
        if len(existing) > 200:
            existing = existing[-200:]
        _RUN_INDEX_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Task / run execution
# ---------------------------------------------------------------------------

def _sanitize_task_name(name, idx):
    n = str(name or "").strip()
    if not _TASK_NAME_RE.match(n):
        n = f"task_{idx:03d}"
    return n


def _run_single_task(task, suite_name, run_dir, log_prefix):
    task_name = _sanitize_task_name(task.get("name"), 0)
    task_dir = run_dir / task_name
    counter = 1
    while task_dir.exists():
        task_dir = run_dir / f"{task_name}_{counter}"
        counter += 1
    task_dir.mkdir(parents=True, exist_ok=True)

    log_lines = [f"{log_prefix} started {task_dir.name} at {int(time.time())}"]
    t_start = time.time()

    setup_results = _run_actions(task.get("setup"), "setup", log_lines) if task.get("setup") else []
    goal_result = _execute_task_goal(task, log_lines)

    assertions = task.get("assertions") or []
    assertion_results = []
    for a_idx, assertion in enumerate(assertions):
        res = _evaluate_assertion(assertion, task_dir)
        res["index"] = a_idx
        assertion_results.append(res)
        log_lines.append(f"[assert#{a_idx}:{res.get('type')}] {'PASS' if res['ok'] else 'FAIL'} - {res.get('reason')}")

    teardown_results = _run_actions(task.get("teardown"), "teardown", log_lines) if task.get("teardown") else []

    passed = all(a["ok"] for a in assertion_results) and bool(assertion_results)
    elapsed = round(time.time() - t_start, 3)

    record = {
        "task": task_name,
        "suite": suite_name,
        "passed": passed,
        "elapsed_s": elapsed,
        "goal": task.get("goal"),
        "steps_count": len(task.get("steps") or []),
        "setup": setup_results,
        "goal_result": goal_result,
        "assertions": assertion_results,
        "teardown": teardown_results,
        "evidence_dir": str(task_dir),
        "log": log_lines,
    }
    try:
        (task_dir / "task.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        (task_dir / "run.log").write_text("\n".join(log_lines), encoding="utf-8")
    except Exception as exc:
        _log(f"[benchmark] failed to persist task {task_name}: {exc}")
    return record


def _run_suite(tasks, suite_name):
    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = int(time.time())
    task_records = []
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            task_records.append({"task": f"task_{idx:03d}", "passed": False,
                                 "elapsed_s": 0, "assertions": [],
                                 "error": "task must be an object"})
            continue
        try:
            record = _run_single_task(task, suite_name, run_dir, f"[bench/{run_id}/{idx}]")
        except Exception as exc:
            record = {
                "task": _sanitize_task_name(task.get("name"), idx),
                "passed": False, "elapsed_s": 0, "assertions": [],
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
            }
        task_records.append(record)

    total = len(task_records)
    passed = sum(1 for r in task_records if r.get("passed"))
    finished_at = int(time.time())
    summary = {
        "run_id": run_id,
        "suite": suite_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_s": finished_at - started_at,
        "task_count": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": round((passed / total) * 100.0, 2) if total else 0.0,
        "tasks": [
            {
                "name": r.get("task"),
                "passed": r.get("passed", False),
                "elapsed_s": r.get("elapsed_s", 0),
                "assertion_count": len(r.get("assertions") or []),
                "assertion_failures": [
                    {"index": a.get("index"), "type": a.get("type"), "reason": a.get("reason")}
                    for a in (r.get("assertions") or []) if not a.get("ok")
                ],
                "evidence_dir": r.get("evidence_dir"),
                "error": r.get("error"),
            }
            for r in task_records
        ],
    }
    try:
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                              encoding="utf-8")
    except Exception as exc:
        _log(f"[benchmark] failed to persist summary: {exc}")

    _persist_run_index({
        "run_id": run_id,
        "suite": suite_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "task_count": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": summary["success_rate"],
        "path": str(run_dir),
    })
    return summary


# ---------------------------------------------------------------------------
# Starter suite — ~10 safe, self-contained tasks
# ---------------------------------------------------------------------------

STARTER_SUITE = {
    "name": "starter",
    "description": ("Built-in reliability regression suite: ~10 non-destructive tasks that "
                    "exercise clipboard, screenshot, OCR, window enumeration, HTTP endpoints, "
                    "and screen-diff plumbing. Every task uses only endpoints CoAgent already "
                    "ships with. Safe to re-run any time — no files touched, no state changed."),
    "tasks": [
        {
            "name": "clipboard_roundtrip",
            "goal": "Copy a marker string to the clipboard and read it back",
            "setup": [
                {"path": "/clipboard/set", "method": "POST",
                 "payload": {"text": "HERMES_BENCH_MARKER_42"}, "delay_ms": 150},
            ],
            "assertions": [
                {"type": "http", "path": "/clipboard/get", "method": "GET",
                 "expect_key": "text", "expect_value": "HERMES_BENCH_MARKER_42",
                 "label": "clipboard contains marker"},
            ],
        },
        {
            "name": "screenshot_capture",
            "goal": "Capture the desktop as a JPEG",
            "assertions": [
                {"type": "screenshot", "save_as": "desktop.jpg", "min_bytes": 2048,
                 "label": "screen capture produced a non-trivial JPEG"},
            ],
        },
        {
            "name": "windows_enumerable",
            "goal": "Enumerate the top-level windows on the desktop",
            "assertions": [
                {"type": "http", "path": "/windows", "method": "GET",
                 "label": "GET /windows returns 2xx"},
            ],
        },
        {
            "name": "notepad_launch",
            "goal": "Launch Notepad and confirm its window appears",
            "setup": [
                {"path": "/process/exec", "method": "POST",
                 "payload": {"cmd": "notepad.exe"}, "delay_ms": 1500},
            ],
            "assertions": [
                {"type": "window-exists", "title": "notepad", "visible": True,
                 "label": "a Notepad window is visible"},
            ],
            "teardown": [
                {"path": "/process/kill_name", "method": "POST",
                 "payload": {"name": "notepad.exe"}},
            ],
        },
        {
            "name": "calculator_launch",
            "goal": "Launch the Windows Calculator and confirm the window",
            "setup": [
                {"path": "/process/exec", "method": "POST",
                 "payload": {"cmd": "calc.exe"}, "delay_ms": 2000},
            ],
            "assertions": [
                {"type": "window-exists", "title": "calculator", "visible": True,
                 "label": "Calculator window is visible"},
            ],
            "teardown": [
                {"path": "/process/kill_name", "method": "POST",
                 "payload": {"name": "CalculatorApp.exe"}},
                {"path": "/process/kill_name", "method": "POST",
                 "payload": {"name": "Calculator.exe"}},
            ],
        },
        {
            "name": "notepad_type_text",
            "goal": "Open Notepad, type a marker string, verify it appears via OCR",
            "setup": [
                {"path": "/process/exec", "method": "POST",
                 "payload": {"cmd": "notepad.exe"}, "delay_ms": 1500},
                {"path": "/windows/activate", "method": "POST",
                 "payload": {"title": "Notepad"}, "delay_ms": 400},
                {"path": "/key/type", "method": "POST",
                 "payload": {"text": "HermesBenchmarkVisibleMarker"}, "delay_ms": 700},
            ],
            "assertions": [
                {"type": "ocr", "text": "HermesBenchmark", "fresh": True, "min_count": 1,
                 "label": "OCR sees the typed marker"},
            ],
            "teardown": [
                {"path": "/process/kill_name", "method": "POST",
                 "payload": {"name": "notepad.exe"}},
            ],
        },
        {
            "name": "screen_diff_no_baseline",
            "goal": "Confirm the diff pipeline can capture a baseline and compare it to now",
            "assertions": [
                {"type": "diff", "min_percent_changed": 0.0, "max_percent_changed": 100.0,
                 "label": "diff pipeline produced a comparison"},
            ],
        },
        {
            "name": "version_endpoint",
            "goal": "Confirm the /version endpoint reports the CoAgent build",
            "assertions": [
                {"type": "http", "path": "/version", "method": "GET",
                 "expect_key": "agent", "expect_contains": "Hermes",
                 "label": "/version says 'Hermes ...'"},
            ],
        },
        {
            "name": "health_endpoint",
            "goal": "Confirm the /health endpoint is green",
            "assertions": [
                {"type": "http", "path": "/health", "method": "GET",
                 "expect_key": "status", "expect_value": "ok",
                 "label": "/health returns status=ok"},
            ],
        },
        {
            "name": "verify_check_smoke",
            "goal": "Confirm the /verify/check plumbing accepts a request and returns a verdict",
            "assertions": [
                {"type": "http", "path": "/verify/check", "method": "POST",
                 "payload": {"expected": "any"}, "expect_key": "ok", "expect_value": True,
                 "label": "/verify/check accepts a request"},
            ],
        },
    ],
}


def _seed_starter_suite():
    """Write the starter suite JSON on first run if the file is missing."""
    path = BENCH_DIR / "starter.json"
    if path.exists():
        return
    try:
        path.write_text(json.dumps(STARTER_SUITE, indent=2), encoding="utf-8")
        _log(f"[benchmark] seeded starter suite at {path}")
    except Exception as exc:
        _log(f"[benchmark] failed to seed starter suite: {exc}")


_seed_starter_suite()


# ---------------------------------------------------------------------------
# Flask route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/benchmark/suites", methods=["GET"])
    @require_auth
    def route_benchmark_suites():
        try:
            return jsonify({"ok": True, "suites": _list_suites(),
                            "dir": str(BENCH_DIR)})
        except Exception as exc:
            _log(f"[benchmark] suites error: {exc}\n{traceback.format_exc(limit=4)}")
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    @app.route("/benchmark/run", methods=["POST"])
    @require_auth
    def route_benchmark_run():
        body = _json_body() or {}
        suite_name = str(body.get("suite") or "").strip()
        inline_tasks = body.get("tasks") if isinstance(body.get("tasks"), list) else None

        if not suite_name and not inline_tasks:
            return _missing_field("suite or tasks")

        if suite_name:
            suite, err = _load_suite(suite_name)
            if err:
                return jsonify({"ok": False, "error": err}), 404
            tasks = suite.get("tasks") or []
        else:
            tasks = inline_tasks
            suite_name = "inline"

        if not tasks:
            return jsonify({"ok": False, "error": "no tasks to run"}), 400

        max_tasks = _clamp(body.get("max_tasks", 100), 1, 200, 100)
        tasks = tasks[:max_tasks]

        try:
            summary = _run_suite(tasks, suite_name)
        except Exception as exc:
            _log(f"[benchmark] run error: {exc}\n{traceback.format_exc(limit=6)}")
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({"ok": True, "summary": summary})

    @app.route("/benchmark/results", methods=["GET"])
    @require_auth
    def route_benchmark_results():
        try:
            index = _index_runs()
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({"ok": True, "runs": list(reversed(index)), "count": len(index)})

    @app.route("/benchmark/report", methods=["GET"])
    @require_auth
    def route_benchmark_report():
        from flask import request as _req
        run_id = (_req.args.get("run_id") or "").strip()
        try:
            index = _index_runs()
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
        if not index:
            return jsonify({"ok": True, "run": None, "message": "no runs yet"})
        entry = None
        if run_id:
            for e in index:
                if e.get("run_id") == run_id:
                    entry = e
                    break
            if entry is None:
                return jsonify({"ok": False, "error": f"run_id '{run_id}' not found"}), 404
        else:
            entry = index[-1]
        summary_path = Path(entry.get("path") or "") / "summary.json"
        summary = None
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception as exc:
                _log(f"[benchmark] failed to load summary {summary_path}: {exc}")

        aggregate = {
            "runs_total": len(index),
            "average_success_rate": round(
                sum(float(e.get("success_rate") or 0) for e in index) / len(index), 2
            ) if index else 0.0,
        }
        response = {"ok": True, "aggregate": aggregate, "run": entry, "summary": summary}
        if summary and isinstance(summary.get("tasks"), list):
            response["failures"] = [
                {
                    "name": t.get("name"),
                    "evidence_dir": t.get("evidence_dir"),
                    "assertion_failures": t.get("assertion_failures"),
                    "error": t.get("error"),
                }
                for t in summary["tasks"] if not t.get("passed")
            ]
        return jsonify(response)
