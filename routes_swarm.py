"""Multi-agent orchestration (swarm mode) routes.

A coordinator that decomposes a complex goal into a task DAG, fans out
independent leaf tasks to parallel sub-agents (each a thin prompt wrapper
over an existing per-domain engine: /agent/exec, /browser/*, /com/*,
/google/*), and merges the results.

Fixed role palette: researcher, browser, office, coder.

Endpoints:
    POST /swarm/run
    GET  /swarm/status/<id>
    GET  /swarm/result/<id>
    GET  /swarm/events/<id>   (SSE, per-agent progress + timeline cards)
    POST /swarm/stop/<id>
    GET  /swarm/list
    GET  /swarm/ping
    GET  /swarm/version
"""

import json
import queue
import re
import threading
import time
import uuid

from flask import Blueprint, jsonify, request, stream_with_context

from shared import (
    COAGENT_DIR,
    _console,
    _json_body,
    _wrap_registered_blueprint_routes,
    sse_pack,
    sse_stream_response,
)

# Reuse the goal runner's local-HTTP helper, auth extractor, JSON parser,
# and SSE authorization check so swarm progress streams the same way.
from routes_copilot_enhanced import (
    _coagent_request,
    _auth_header,
    _first_json_value,
    _eventsource_authorized,
)


swarm_bp = Blueprint("swarm", __name__)

SWARM_VERSION = "1.0"
MAX_CONCURRENT_WORKERS = 3   # mirrors MAX_CONCURRENT_GOALS default
MAX_STORED_RUNS = 30
MAX_RUN_EVENTS = 500
MAX_RUN_LOG_ENTRIES = 250
MAX_TASKS = 12
MAX_MERGE_INPUT_CHARS = 4000
DEFAULT_TIMEOUT = 300

ROLE_PALETTE = ("researcher", "browser", "office", "coder")
ROLE_SET = set(ROLE_PALETTE)
DEFAULT_ROLE = "researcher"

ROLE_ICONS = {
    "researcher": "\U0001F50E",   # magnifying glass
    "browser": "\U0001F310",      # globe
    "office": "\U0001F4CA",       # bar chart
    "coder": "\U0001F4BB",        # laptop
    "merge": "\U0001F9E9",        # puzzle
}

STATUS_ICONS = {
    "queued": "\U0001F7E2",
    "planning": "\U0001F7E1",
    "running": "\U0001F535",
    "completed": "✅",
    "failed": "\U0001F534",
    "stopped": "\U0001F534",
    "stopping": "\U0001F7E1",
    "pending": "⏳",
    "blocked": "⏳",
    "ok": "✅",
    "error": "❌",
}

LOG_ICONS = {
    "info": "\U0001F7E2",
    "planning": "\U0001F7E1",
    "action": "\U0001F680",
    "success": "✅",
    "warn": "\U0001F7E1",
    "error": "❌",
    "running": "\U0001F535",
}

TERMINAL_STATES = {"completed", "failed", "stopped"}

_RUNS = {}
_RUN_ORDER = []
_RUNS_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _now():
    return time.time()


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or _now()))


def _clock(ts=None):
    return time.strftime("%H:%M:%S", time.localtime(ts or _now()))


def _short_text(value, limit=200, fallback=""):
    text = str(value if value is not None else fallback).strip()
    if not text:
        text = str(fallback or "").strip()
    if len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def _clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


# --------------------------------------------------------------------------
# Event / log emission (same shape as goal runner: sse_pack frames)
# --------------------------------------------------------------------------

def _put_event(client_queue, event):
    try:
        client_queue.put_nowait(event)
        return True
    except queue.Full:
        try:
            client_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            client_queue.put_nowait(event)
            return True
        except queue.Full:
            return False


def _emit(run_id, event_type, data):
    dead = []
    event = None
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return None
        seq = int(run.get("event_seq") or 0) + 1
        run["event_seq"] = seq
        event = {
            "id": seq,
            "event": event_type,
            "data": data,
            "created_at": _now(),
        }
        events = run.setdefault("events", [])
        events.append(event)
        if len(events) > MAX_RUN_EVENTS:
            del events[:-MAX_RUN_EVENTS]
        subs = list(run.setdefault("subscribers", set()))
    for q in subs:
        if not _put_event(q, event):
            dead.append(q)
    if dead:
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
            if run:
                subs_set = run.setdefault("subscribers", set())
                for q in dead:
                    subs_set.discard(q)
    return event


def _log(run_id, level, message, icon=None):
    ts = _now()
    entry = {
        "time": _clock(ts),
        "timestamp": ts,
        "level": str(level or "info"),
        "icon": icon or LOG_ICONS.get(str(level or "info"), "\U0001F7E2"),
        "message": _short_text(message, 260),
    }
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return entry
        log = run.setdefault("log", [])
        log.append(entry)
        if len(log) > MAX_RUN_LOG_ENTRIES:
            del log[:-MAX_RUN_LOG_ENTRIES]
        run["updated_at"] = ts
    _emit(run_id, "log", entry)
    return entry


# --------------------------------------------------------------------------
# Planner: decompose goal into a task DAG
# --------------------------------------------------------------------------

def _plan_prompt(goal, max_tasks):
    roles = ", ".join(ROLE_PALETTE)
    return (
        "You are a planning coordinator for a multi-agent desktop swarm. "
        "Decompose the user goal into a small DAG of independent sub-tasks. "
        "Return ONLY a JSON object of the shape: "
        '{"reasoning":"...","tasks":[{"id":"t1","role":"researcher",'
        '"prompt":"...","depends_on":[]}]}. '
        f"Allowed roles: {roles}. "
        "Prefer parallelism — mark tasks independent (empty depends_on) whenever possible. "
        "Use researcher for open web/domain lookups, browser for concrete site navigation, "
        "office for Excel/Word/COM tasks, coder for code generation/editing. "
        "Keep prompts short and self-contained (a sub-agent will see only its own prompt "
        "plus upstream task summaries).\n\n"
        f"Goal: {goal}\n"
        f"Maximum tasks: {max_tasks}"
    )


def _normalize_tasks(raw_tasks, max_tasks):
    if not isinstance(raw_tasks, list):
        raise ValueError("tasks must be a list")
    tasks = []
    seen_ids = set()
    for i, raw in enumerate(raw_tasks[:max_tasks]):
        if not isinstance(raw, dict):
            continue
        prompt = str(raw.get("prompt") or raw.get("task") or "").strip()
        if not prompt:
            continue
        role = str(raw.get("role") or DEFAULT_ROLE).strip().lower()
        if role not in ROLE_SET:
            role = DEFAULT_ROLE
        tid = str(raw.get("id") or f"t{i + 1}").strip() or f"t{i + 1}"
        if tid in seen_ids:
            tid = f"{tid}_{i + 1}"
        seen_ids.add(tid)
        raw_deps = raw.get("depends_on") or raw.get("deps") or []
        if not isinstance(raw_deps, list):
            raw_deps = []
        deps = [str(d).strip() for d in raw_deps if str(d).strip()]
        tasks.append({
            "id": tid,
            "role": role,
            "prompt": prompt,
            "depends_on": deps,
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "attempt": 0,
        })
    if not tasks:
        raise ValueError("no valid tasks in plan")
    # Drop dep references that point at unknown ids (planner drift).
    valid_ids = {t["id"] for t in tasks}
    for t in tasks:
        t["depends_on"] = [d for d in t["depends_on"] if d in valid_ids and d != t["id"]]
    return tasks


def _local_fallback_plan(goal, max_tasks):
    """Conservative fallback plan if the agent gateway can't decompose."""
    text = str(goal or "").lower()
    tasks = []
    idx = 1
    def add(role, prompt, deps=None):
        nonlocal idx
        tasks.append({
            "id": f"t{idx}",
            "role": role,
            "prompt": prompt,
            "depends_on": deps or [],
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "attempt": 0,
        })
        idx += 1

    if re.search(r"\b(research|find|look up|competitor|price|pricing|market)\b", text):
        add("researcher", f"Research and summarize key facts for: {goal}")
    if re.search(r"\b(browse|site|url|website|open|navigate|scrape)\b", text):
        add("browser", f"Use the browser to gather data relevant to: {goal}")
    if re.search(r"\b(excel|spreadsheet|word|doc|com|office|xlsx|docx|csv)\b", text):
        add("office", f"Use Excel/COM to produce the deliverable for: {goal}",
            deps=[t["id"] for t in tasks if t["role"] in {"researcher", "browser"}])
    if re.search(r"\b(code|script|python|refactor|implement|function|patch)\b", text):
        add("coder", f"Write or edit code as required for: {goal}",
            deps=[t["id"] for t in tasks if t["role"] == "researcher"])
    if not tasks:
        add("researcher", f"Research and summarize: {goal}")
    return tasks[:max_tasks]


def _plan_via_agent(goal, max_tasks, auth_header, agent=None, model=None):
    payload = {
        "prompt": _plan_prompt(goal, max_tasks),
        "agent": agent or "codex",
        "model": model,
        "timeout": 90,
        "workdir": str(COAGENT_DIR),
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    try:
        response = _coagent_request(
            "POST", "/agent/exec", payload,
            auth_header=auth_header, timeout=120,
        )
    except Exception as exc:
        _console(f"[swarm] planner request failed: {type(exc).__name__}: {exc}")
        response = {"error": str(exc)}
    output = ""
    if isinstance(response, dict):
        output = (
            response.get("output")
            or response.get("stdout")
            or response.get("text")
            or ""
        )
    reasoning = ""
    if output:
        try:
            parsed = _first_json_value(output)
            if isinstance(parsed, dict):
                reasoning = str(parsed.get("reasoning") or parsed.get("summary") or "")
                raw_tasks = parsed.get("tasks")
            else:
                raw_tasks = parsed
            tasks = _normalize_tasks(raw_tasks, max_tasks)
            return tasks, {
                "source": "agent_gateway",
                "reasoning": reasoning,
                "agent_response": response,
            }
        except Exception as exc:
            _console(f"[swarm] planner parse failed: {type(exc).__name__}: {exc}")
    tasks = _local_fallback_plan(goal, max_tasks)
    return tasks, {
        "source": "local_fallback",
        "reasoning": "Local fallback plan (agent decomposition unavailable).",
        "agent_response": response,
    }


# --------------------------------------------------------------------------
# DAG execution: worker pool with dependency scheduling
# --------------------------------------------------------------------------

def _upstream_summaries(task, all_tasks):
    """Compact bag of completed upstream task outputs for prompt context."""
    dep_ids = set(task.get("depends_on") or [])
    if not dep_ids:
        return ""
    lines = []
    for t in all_tasks:
        if t["id"] not in dep_ids:
            continue
        result = t.get("result")
        summary = ""
        if isinstance(result, dict):
            summary = str(
                result.get("summary")
                or result.get("output")
                or result.get("text")
                or json.dumps(result, ensure_ascii=False)
            )
        elif result is not None:
            summary = str(result)
        summary = _short_text(summary, 600)
        if summary:
            lines.append(f"[{t['id']} / {t['role']}]: {summary}")
    return "\n".join(lines)


def _role_prompt(task, upstream):
    role = task.get("role", DEFAULT_ROLE)
    base = task.get("prompt", "")
    context = f"\n\nUpstream context:\n{upstream}" if upstream else ""
    if role == "researcher":
        return (
            "You are a research sub-agent. Gather concise, factual findings "
            "relevant to the task. Return a short structured summary at the "
            "end starting with the line 'SUMMARY:'.\n\n"
            f"Task: {base}{context}"
        )
    if role == "browser":
        return (
            "You are a browser automation sub-agent. Use the CoAgent HTTP API "
            "at http://127.0.0.1 (endpoints /browser/navigate, /browser/extract, "
            "/browser/click, /browser/fill, /browser/screenshot) to complete the "
            "task. Return a short 'SUMMARY:' block with the extracted data.\n\n"
            f"Task: {base}{context}"
        )
    if role == "office":
        return (
            "You are an Office/COM sub-agent. Use the CoAgent HTTP API at "
            "http://127.0.0.1 (endpoints /com/powershell, /com/com-object, "
            "/com/wmi, /com/registry) to drive Excel/Word/Outlook via COM. "
            "Return a short 'SUMMARY:' block with what was produced (paths, "
            "sheet names, row counts).\n\n"
            f"Task: {base}{context}"
        )
    if role == "coder":
        return (
            "You are a coding sub-agent. Produce or edit code as required. "
            "Return a short 'SUMMARY:' block describing files touched and "
            "the change intent.\n\n"
            f"Task: {base}{context}"
        )
    return f"Task: {base}{context}"


def _extract_summary(output_text):
    if not output_text:
        return ""
    match = re.search(r"SUMMARY:\s*(.+)$", output_text, re.DOTALL | re.IGNORECASE)
    if match:
        return _short_text(match.group(1).strip(), 800)
    # Fallback: last non-empty paragraph.
    parts = [p.strip() for p in re.split(r"\n\s*\n", output_text.strip()) if p.strip()]
    return _short_text(parts[-1], 800) if parts else _short_text(output_text, 800)


def _invoke_sub_agent(task, upstream, auth_header, agent=None, model=None, timeout=None):
    prompt = _role_prompt(task, upstream)
    payload = {
        "prompt": prompt,
        "agent": agent or "codex",
        "model": model,
        "timeout": int(timeout or 180),
        "workdir": str(COAGENT_DIR),
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    response = _coagent_request(
        "POST", "/agent/exec", payload,
        auth_header=auth_header, timeout=int(timeout or 180) + 30,
    )
    output = ""
    if isinstance(response, dict):
        output = (
            response.get("output")
            or response.get("stdout")
            or response.get("text")
            or ""
        )
        if not output and response.get("error"):
            return {
                "status": "error",
                "error": _short_text(response.get("error"), 240),
                "raw": response,
            }
    summary = _extract_summary(output)
    return {
        "status": "ok",
        "summary": summary,
        "output": _short_text(output, 4000),
        "raw": response,
    }


def _task_card(task):
    """Timeline card for a single sub-agent task (dashboard-compatible)."""
    role = task.get("role", DEFAULT_ROLE)
    status = task.get("status", "pending")
    ui_status = "done" if status == "ok" else status
    card = {
        "id": task.get("id"),
        "role": role,
        "role_icon": ROLE_ICONS.get(role, "\U0001F916"),
        "label": _short_text(task.get("prompt", ""), 96),
        "status": ui_status,
        "raw_status": status,
        "status_icon": STATUS_ICONS.get(status, "⏳"),
        "depends_on": list(task.get("depends_on") or []),
        "attempt": task.get("attempt", 0),
    }
    if task.get("duration_ms") is not None:
        card["duration_ms"] = task["duration_ms"]
    if task.get("error"):
        card["error"] = _short_text(task["error"], 200)
    result = task.get("result")
    if isinstance(result, dict) and result.get("summary"):
        card["summary"] = _short_text(result["summary"], 240)
    return card


def _progress(tasks):
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("status") in {"ok", "error"})
    return {"current": done, "total": total}


def _status_text(status, progress):
    total = progress.get("total", 0)
    current = progress.get("current", 0)
    if status == "queued":
        return "Queued"
    if status == "planning":
        return "Planning"
    if status == "running":
        return f"Running ({current}/{total} tasks done)" if total else "Running"
    if status == "completed":
        return f"Completed {total}/{total} tasks" if total else "Completed"
    if status == "failed":
        return f"Failed at {current}/{total}" if total else "Failed"
    if status == "stopped":
        return f"Stopped at {current}/{total}" if total else "Stopped"
    if status == "stopping":
        return "Stopping"
    return "Idle"


def _timeline(run):
    tasks = run.get("tasks", [])
    cards = [_task_card(t) for t in tasks]
    progress = _progress(tasks)
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    duration_seconds = 0
    if started_at:
        duration_seconds = round((finished_at or _now()) - started_at, 2)
    status = run.get("status", "idle")
    return {
        "run_id": run.get("run_id"),
        "goal": run.get("goal", ""),
        "status": status,
        "status_icon": STATUS_ICONS.get(status, "\U0001F7E2"),
        "status_text": _status_text(status, progress),
        "progress": progress,
        "duration_seconds": duration_seconds,
        "tasks": cards,
        "reasoning": run.get("reasoning", ""),
        "plan_source": run.get("plan_source", ""),
        "max_workers": run.get("max_workers"),
        "created_at": run.get("created_at"),
        "started_at": started_at,
        "finished_at": finished_at,
        "log": list(run.get("log") or []),
        "error": run.get("error"),
        "final": run.get("final"),
    }


def _emit_timeline(run_id):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return None
        payload = _timeline(run)
    return _emit(run_id, "timeline", payload)


def _snapshot(run):
    internal = {"stop_event", "subscribers", "events", "event_seq", "thread"}
    return {k: v for k, v in run.items() if k not in internal}


def _complete_payload(run):
    tl = _timeline(run)
    return {
        "status": tl["status"],
        "total": tl["progress"]["total"],
        "completed": sum(1 for t in tl["tasks"] if t["status"] == "done"),
        "failed": sum(1 for t in tl["tasks"] if t["status"] == "error"),
        "duration": tl["duration_seconds"],
        "final": tl.get("final"),
    }


def _mark_complete(run_id, status, error=None):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return None
        run["status"] = status
        run["finished_at"] = _now()
        run["updated_at"] = run["finished_at"]
        if error:
            run["error"] = error
        payload = _complete_payload(run)
    _emit_timeline(run_id)
    _emit(run_id, "swarm_complete", payload)
    return payload


# --------------------------------------------------------------------------
# Merge / aggregation
# --------------------------------------------------------------------------

def _merge_via_agent(goal, tasks, auth_header, agent=None, model=None):
    ok_tasks = [t for t in tasks if t.get("status") == "ok"]
    if not ok_tasks:
        return {
            "summary": "No sub-agent produced a usable result.",
            "source": "local_fallback",
        }
    lines = []
    total = 0
    for t in ok_tasks:
        result = t.get("result") or {}
        summary = result.get("summary") or result.get("output") or ""
        chunk = f"[{t['id']} / {t['role']}]: {_short_text(summary, 500)}"
        if total + len(chunk) > MAX_MERGE_INPUT_CHARS:
            break
        lines.append(chunk)
        total += len(chunk)
    context = "\n".join(lines)
    prompt = (
        "You are the swarm aggregator. Combine the sub-agent findings below "
        "into one concise final answer for the user. Keep it under 400 words.\n\n"
        f"Original goal: {goal}\n\n"
        f"Sub-agent results:\n{context}"
    )
    payload = {
        "prompt": prompt,
        "agent": agent or "codex",
        "model": model,
        "timeout": 90,
        "workdir": str(COAGENT_DIR),
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    try:
        response = _coagent_request(
            "POST", "/agent/exec", payload,
            auth_header=auth_header, timeout=120,
        )
    except Exception as exc:
        _console(f"[swarm] merge request failed: {type(exc).__name__}: {exc}")
        response = {"error": str(exc)}
    output = ""
    if isinstance(response, dict):
        output = (
            response.get("output")
            or response.get("stdout")
            or response.get("text")
            or ""
        )
    if output.strip():
        return {"summary": _short_text(output.strip(), 3000), "source": "agent_gateway"}
    # Fallback: local join of task summaries.
    joined = "\n\n".join(
        f"- {t['id']} ({t['role']}): "
        f"{_short_text((t.get('result') or {}).get('summary') or '', 300)}"
        for t in ok_tasks
    )
    return {
        "summary": f"Aggregated sub-agent results:\n\n{joined}",
        "source": "local_fallback",
    }


# --------------------------------------------------------------------------
# DAG runner
# --------------------------------------------------------------------------

def _ready_tasks(tasks):
    done_ids = {t["id"] for t in tasks if t.get("status") in {"ok", "error"}}
    failed_ids = {t["id"] for t in tasks if t.get("status") == "error"}
    ready = []
    for t in tasks:
        if t.get("status") != "pending":
            continue
        deps = set(t.get("depends_on") or [])
        if deps & failed_ids:
            t["status"] = "error"
            t["error"] = f"upstream dependency failed: {sorted(deps & failed_ids)}"
            continue
        if deps.issubset(done_ids):
            ready.append(t)
    return ready


def _run_dag(run_id, auth_header):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return
        run["status"] = "planning"
        run["started_at"] = _now()
        run["updated_at"] = run["started_at"]
        stop_event = run["stop_event"]
        goal_text = run["goal"]
        max_tasks = run.get("max_tasks", MAX_TASKS)
        max_workers = run.get("max_workers", MAX_CONCURRENT_WORKERS)
        agent = run.get("agent")
        model = run.get("model")
        task_timeout = run.get("task_timeout", 180)

    _log(run_id, "planning", f'Planning swarm goal: "{goal_text}"', "\U0001F7E1")
    _emit(run_id, "swarm_status", {"status": "planning", "icon": STATUS_ICONS["planning"]})

    try:
        tasks, meta = _plan_via_agent(goal_text, max_tasks, auth_header,
                                      agent=agent, model=model)
        with _RUNS_LOCK:
            run = _RUNS[run_id]
            run["tasks"] = tasks
            run["reasoning"] = meta.get("reasoning", "")
            run["plan_source"] = meta.get("source", "")
            run["status"] = "running"
            run["updated_at"] = _now()
        _log(run_id, "info",
             f"Planner produced {len(tasks)} tasks ({meta.get('source')})",
             "\U0001F7E2")
        _emit(run_id, "swarm_planned", {"total": len(tasks), "source": meta.get("source")})
        _emit(run_id, "swarm_status", {"status": "running", "icon": STATUS_ICONS["running"]})
        _emit_timeline(run_id)

        # Worker pool: dispatch ready tasks up to max_workers at a time.
        active = {}  # task_id -> thread
        results_lock = threading.Lock()

        def worker(task):
            attempt = 1
            start = _now()
            with _RUNS_LOCK:
                task["status"] = "running"
                task["started_at"] = start
                task["attempt"] = attempt
                snapshot = list(run["tasks"])
            upstream = _upstream_summaries(task, snapshot)
            _log(run_id, "action",
                 f"[{task['id']} / {task['role']}] {_short_text(task['prompt'], 96)}",
                 ROLE_ICONS.get(task["role"], "\U0001F680"))
            _emit(run_id, "task_start", {
                "id": task["id"],
                "role": task["role"],
                "icon": ROLE_ICONS.get(task["role"], "\U0001F916"),
                "label": _short_text(task["prompt"], 96),
            })
            _emit_timeline(run_id)
            try:
                if stop_event.is_set():
                    outcome = {"status": "error", "error": "swarm stopped"}
                else:
                    outcome = _invoke_sub_agent(
                        task, upstream, auth_header,
                        agent=agent, model=model, timeout=task_timeout,
                    )
            except Exception as exc:
                _console(f"[swarm] task {task['id']} raised: "
                         f"{type(exc).__name__}: {exc}")
                outcome = {"status": "error",
                           "error": f"{type(exc).__name__}: {exc}"}
            duration_ms = int(round((_now() - start) * 1000))
            with results_lock, _RUNS_LOCK:
                task["finished_at"] = _now()
                task["duration_ms"] = duration_ms
                if outcome.get("status") == "ok":
                    task["status"] = "ok"
                    task["result"] = {
                        "summary": outcome.get("summary", ""),
                        "output": outcome.get("output", ""),
                    }
                else:
                    task["status"] = "error"
                    task["error"] = _short_text(outcome.get("error", "unknown error"), 240)
            if task["status"] == "ok":
                _log(run_id, "success",
                     f"[{task['id']}] done in {duration_ms} ms — "
                     f"{_short_text(outcome.get('summary', ''), 96)}",
                     "✅")
                _emit(run_id, "task_complete", {
                    "id": task["id"], "duration_ms": duration_ms,
                    "summary": _short_text(outcome.get("summary", ""), 240),
                })
            else:
                _log(run_id, "error",
                     f"[{task['id']}] failed: {task['error']}", "❌")
                _emit(run_id, "task_error", {
                    "id": task["id"], "error": task["error"],
                })
            _emit_timeline(run_id)

        # Main scheduling loop.
        while True:
            if stop_event.is_set():
                break
            with _RUNS_LOCK:
                current_tasks = list(run["tasks"])
            # Reap finished threads.
            for tid, th in list(active.items()):
                if not th.is_alive():
                    active.pop(tid, None)
            pending_left = any(t.get("status") == "pending" for t in current_tasks)
            if not pending_left and not active:
                break
            if pending_left:
                with _RUNS_LOCK:
                    ready = _ready_tasks(current_tasks)
            else:
                ready = []
            launched = 0
            for t in ready:
                if len(active) >= max_workers:
                    break
                if t["id"] in active:
                    continue
                th = threading.Thread(
                    target=worker, args=(t,),
                    name=f"swarm-{run_id[:6]}-{t['id']}", daemon=True,
                )
                active[t["id"]] = th
                th.start()
                launched += 1
            if not launched and not active:
                # Nothing ready to run and nothing active — every remaining
                # pending task is blocked by a failed dependency (already
                # marked error in _ready_tasks). Exit.
                break
            time.sleep(0.15)

        # Wait for any last active threads (in case of stop event triggering
        # while workers were still finishing).
        for th in list(active.values()):
            th.join(timeout=5)

        with _RUNS_LOCK:
            tasks_snapshot = list(run["tasks"])
        any_ok = any(t.get("status") == "ok" for t in tasks_snapshot)

        if stop_event.is_set():
            _log(run_id, "warn", "Swarm stopped by request", "\U0001F7E1")
            _mark_complete(run_id, "stopped")
            return

        # Merge step.
        _emit(run_id, "swarm_merge", {"icon": ROLE_ICONS["merge"]})
        _log(run_id, "info", "Merging sub-agent results", ROLE_ICONS["merge"])
        merged = _merge_via_agent(goal_text, tasks_snapshot, auth_header,
                                  agent=agent, model=model)
        with _RUNS_LOCK:
            run["final"] = merged

        all_failed = all(t.get("status") == "error" for t in tasks_snapshot)
        if all_failed or not any_ok:
            _log(run_id, "error", "All sub-agents failed", "❌")
            _mark_complete(run_id, "failed", error="all sub-agents failed")
        else:
            _log(run_id, "success",
                 f"Swarm completed: {sum(1 for t in tasks_snapshot if t.get('status') == 'ok')}"
                 f"/{len(tasks_snapshot)} tasks ok", "✅")
            _mark_complete(run_id, "completed")

    except Exception as exc:
        _console(f"[swarm] run {run_id} crashed: {type(exc).__name__}: {exc}")
        message = f"{type(exc).__name__}: {exc}"
        _log(run_id, "error", f"Swarm crashed: {message}", "❌")
        _mark_complete(run_id, "failed", error=message)


# --------------------------------------------------------------------------
# Store management
# --------------------------------------------------------------------------

def _active_run_count():
    with _RUNS_LOCK:
        return sum(1 for r in _RUNS.values()
                   if r.get("status") in {"queued", "planning", "running", "stopping"})


def _trim_runs():
    with _RUNS_LOCK:
        while len(_RUN_ORDER) > MAX_STORED_RUNS:
            old_id = _RUN_ORDER.pop(0)
            run = _RUNS.get(old_id)
            if run and run.get("status") in {"queued", "planning", "running", "stopping"}:
                _RUN_ORDER.append(old_id)
                break
            _RUNS.pop(old_id, None)


# --------------------------------------------------------------------------
# HTTP endpoints
# --------------------------------------------------------------------------

@swarm_bp.route("/swarm/ping", methods=["GET"])
def route_swarm_ping():
    return jsonify({
        "status": "pong",
        "agent": "swarm",
        "version": SWARM_VERSION,
        "roles": list(ROLE_PALETTE),
    })


@swarm_bp.route("/swarm/version", methods=["GET"])
def route_swarm_version():
    return jsonify({
        "agent": "swarm",
        "version": SWARM_VERSION,
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "max_tasks": MAX_TASKS,
        "roles": list(ROLE_PALETTE),
    })


@swarm_bp.route("/swarm/run", methods=["POST"])
def route_swarm_run():
    data = _json_body()
    goal_text = str(data.get("goal") or "").strip()
    if not goal_text:
        return jsonify({"error": "goal is required"}), 400
    max_workers = _clamp_int(data.get("max_workers"), MAX_CONCURRENT_WORKERS, 1, 8)
    max_tasks = _clamp_int(data.get("max_tasks"), MAX_TASKS, 1, 24)
    task_timeout = _clamp_int(data.get("task_timeout"), 180, 30, 900)

    if _active_run_count() >= MAX_CONCURRENT_WORKERS:
        return jsonify({
            "error": "maximum concurrent swarm runs reached",
            "limit": MAX_CONCURRENT_WORKERS,
        }), 429

    run_id = uuid.uuid4().hex
    stop_event = threading.Event()
    auth = _auth_header(request.headers.get("Authorization", ""))
    record = {
        "id": run_id,
        "run_id": run_id,
        "goal": goal_text,
        "status": "queued",
        "tasks": [],
        "log": [],
        "events": [],
        "event_seq": 0,
        "subscribers": set(),
        "max_workers": max_workers,
        "max_tasks": max_tasks,
        "task_timeout": task_timeout,
        "created_at": _now(),
        "created_at_iso": _iso(),
        "updated_at": _now(),
        "started_at": None,
        "finished_at": None,
        "agent": data.get("agent") or "codex",
        "model": data.get("model"),
        "reasoning": "",
        "plan_source": "",
        "final": None,
        "error": None,
        "stop_event": stop_event,
    }
    thread = threading.Thread(
        target=_run_dag, args=(run_id, auth),
        name=f"swarm-run-{run_id[:8]}", daemon=True,
    )
    record["thread"] = thread
    with _RUNS_LOCK:
        _RUNS[run_id] = record
        _RUN_ORDER.append(run_id)
    _log(run_id, "info", f'Queued swarm goal: "{goal_text}"', "\U0001F7E2")
    thread.start()
    _trim_runs()
    return jsonify({
        "run_id": run_id,
        "status": "queued",
        "goal": goal_text,
        "max_workers": max_workers,
        "events_url": f"/swarm/events/{run_id}",
        "status_url": f"/swarm/status/{run_id}",
        "result_url": f"/swarm/result/{run_id}",
    }), 202


@swarm_bp.route("/swarm/status/<run_id>", methods=["GET"])
def route_swarm_status(run_id):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return jsonify({"error": "swarm run not found", "run_id": run_id}), 404
        return jsonify(_timeline(run))


@swarm_bp.route("/swarm/result/<run_id>", methods=["GET"])
def route_swarm_result(run_id):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return jsonify({"error": "swarm run not found", "run_id": run_id}), 404
        status = run.get("status", "queued")
        if status not in TERMINAL_STATES:
            return jsonify({
                "run_id": run_id,
                "status": status,
                "ready": False,
                "message": "swarm run still in progress",
            }), 202
        payload = {
            "run_id": run_id,
            "status": status,
            "ready": True,
            "goal": run.get("goal", ""),
            "final": run.get("final"),
            "duration_seconds": round(
                (run.get("finished_at") or _now())
                - (run.get("started_at") or run.get("created_at") or _now()),
                2,
            ),
            "tasks": [
                {
                    "id": t.get("id"),
                    "role": t.get("role"),
                    "status": t.get("status"),
                    "summary": (t.get("result") or {}).get("summary") if isinstance(t.get("result"), dict) else None,
                    "error": t.get("error"),
                    "duration_ms": t.get("duration_ms"),
                }
                for t in run.get("tasks", [])
            ],
            "error": run.get("error"),
        }
    return jsonify(payload)


@swarm_bp.route("/swarm/stop/<run_id>", methods=["POST"])
def route_swarm_stop(run_id):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return jsonify({"error": "swarm run not found", "run_id": run_id}), 404
        run["stop_event"].set()
        if run.get("status") in {"queued", "planning", "running"}:
            run["status"] = "stopping"
        run["updated_at"] = _now()
    _log(run_id, "warn", "Stop requested", "\U0001F7E1")
    _emit(run_id, "swarm_status", {"status": "stopping", "icon": STATUS_ICONS["stopping"]})
    _emit_timeline(run_id)
    with _RUNS_LOCK:
        return jsonify(_snapshot(_RUNS[run_id]))


@swarm_bp.route("/swarm/list", methods=["GET"])
def route_swarm_list():
    with _RUNS_LOCK:
        runs = []
        for rid in list(_RUN_ORDER):
            run = _RUNS.get(rid)
            if not run:
                continue
            runs.append({
                "run_id": run.get("run_id"),
                "goal": _short_text(run.get("goal", ""), 96),
                "status": run.get("status"),
                "task_count": len(run.get("tasks") or []),
                "created_at": run.get("created_at"),
                "finished_at": run.get("finished_at"),
            })
        return jsonify({
            "runs": runs,
            "active": _active_run_count(),
            "stored": len(_RUNS),
        })


@swarm_bp.route("/swarm/events/<run_id>", methods=["GET"])
def route_swarm_events(run_id):
    if not _eventsource_authorized():
        return jsonify({"error": "Unauthorized - provide Bearer token"}), 401
    client_queue = queue.Queue(maxsize=100)
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            return jsonify({"error": "swarm run not found", "run_id": run_id}), 404
        run.setdefault("subscribers", set()).add(client_queue)
        initial = _timeline(run)
        terminal = run.get("status") in TERMINAL_STATES
        complete_payload = _complete_payload(run) if terminal else None

    def generate():
        try:
            yield sse_pack("timeline", initial, retry=1500)
            if complete_payload is not None:
                yield sse_pack("swarm_complete", complete_payload)
                return
            while True:
                try:
                    event = client_queue.get(timeout=20)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield sse_pack(event.get("event"), event.get("data"),
                               event_id=event.get("id"))
                if event.get("event") == "swarm_complete":
                    return
        finally:
            with _RUNS_LOCK:
                run = _RUNS.get(run_id)
                if run:
                    run.setdefault("subscribers", set()).discard(client_queue)

    return sse_stream_response(
        stream_with_context(generate()),
        headers={"X-Swarm-Run-Id": run_id},
    )


route_swarm_events._hermes_auth_wrapped = True


def register_routes(app, state, require_auth):
    app.register_blueprint(swarm_bp)
    _wrap_registered_blueprint_routes(app, swarm_bp.name, require_auth)
    state.swarm = {
        "version": SWARM_VERSION,
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "roles": list(ROLE_PALETTE),
    }
