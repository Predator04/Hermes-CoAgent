"""Background autonomous agent mode.

Runs a sequence of automation steps in a worker thread without stealing focus
from the user. Reuses the focus-safe primitives from routes_background
(UIA InvokePattern, PostMessage) and, when available, the CUA bridge for
higher-level actions such as typing or clicking at coordinates.

Endpoints:
  POST /bg/run    - start an autonomous task in the background
  GET  /bg/status - inspect the current or last-completed task
  POST /bg/stop   - signal the running task to stop between steps

All Windows-only dependencies are imported inside try/except so the Linux
syntax-check CI does not fail.
"""

import threading
import time
import uuid

from flask import jsonify

from shared import _console, _json_body, _log


try:
    from routes_background import (
        _find_window_by_title,
        focus_safe_show,
        type_into_window_post,
        type_via_uia,
        uia_invoke_element,
    )
    _HAS_BG_PRIMS = True
except Exception as _bg_import_error:
    _HAS_BG_PRIMS = False
    _BG_IMPORT_ERROR = str(_bg_import_error)

    def _find_window_by_title(_title):
        return 0

    def focus_safe_show(_hwnd):
        return False

    def type_into_window_post(_hwnd, _text, _delay_ms=10):
        return {"success": False, "error": "routes_background unavailable"}

    def type_via_uia(_hwnd, _text):
        return {"success": False, "error": "routes_background unavailable"}

    def uia_invoke_element(_find_by, _value):
        return {"success": False, "error": "routes_background unavailable"}


try:
    from cua_bridge import cua_available, cua_call
    _HAS_CUA = True
except Exception:
    _HAS_CUA = False

    def cua_available():
        return False

    def cua_call(_tool, _data):
        raise FileNotFoundError("CUA bridge unavailable")


_STATE_LOCK = threading.Lock()
_STOP_EVENT = threading.Event()
_WORKER = {"thread": None}

_STATE = {
    "run_id": None,
    "task": "",
    "active": False,
    "status": "idle",
    "started_at": 0.0,
    "ended_at": 0.0,
    "steps_total": 0,
    "steps_done": 0,
    "last_action": "",
    "last_error": None,
    "results": [],
}

_MAX_RESULTS = 200
_MAX_STEPS = 500


def _snapshot_state():
    with _STATE_LOCK:
        snap = dict(_STATE)
        snap["results"] = list(_STATE["results"])
    if snap["started_at"]:
        end = snap["ended_at"] or time.time()
        snap["elapsed_seconds"] = round(end - snap["started_at"], 2)
    else:
        snap["elapsed_seconds"] = 0.0
    snap["stopping"] = _STOP_EVENT.is_set() and snap["active"]
    return snap


def _record_result(entry):
    with _STATE_LOCK:
        _STATE["steps_done"] += 1
        _STATE["last_action"] = entry.get("type", "")
        if not entry.get("success"):
            _STATE["last_error"] = entry.get("error")
        _STATE["results"].append(entry)
        if len(_STATE["results"]) > _MAX_RESULTS:
            _STATE["results"] = _STATE["results"][-_MAX_RESULTS:]


def _set_status(status, *, ended=False, error=None):
    with _STATE_LOCK:
        _STATE["status"] = status
        if error is not None:
            _STATE["last_error"] = error
        if ended:
            _STATE["active"] = False
            _STATE["ended_at"] = time.time()


def _resolve_hwnd(step, context):
    """Return an hwnd based on the step or the shared worker context."""
    hwnd = step.get("hwnd") or context.get("hwnd")
    if hwnd:
        try:
            return int(hwnd)
        except (TypeError, ValueError):
            return 0
    title = step.get("window") or step.get("title") or context.get("window", "")
    if title and _HAS_BG_PRIMS:
        found = _find_window_by_title(str(title))
        if found:
            context["hwnd"] = found
            context["window"] = title
            return found
    return 0


def _run_step(step, context):
    """Execute a single step. Returns a result dict."""
    action = str(step.get("type") or step.get("action") or "").strip().lower()
    entry = {"type": action}

    if action == "find_window":
        title = step.get("title") or step.get("window") or ""
        if not title:
            return {**entry, "success": False, "error": "missing title"}
        hwnd = _find_window_by_title(str(title)) if _HAS_BG_PRIMS else 0
        if hwnd:
            context["hwnd"] = hwnd
            context["window"] = title
            if step.get("show", True):
                focus_safe_show(hwnd)
            return {**entry, "success": True, "hwnd": hwnd, "title": title}
        return {**entry, "success": False, "error": f"window not found: {title}"}

    if action == "show_window":
        hwnd = _resolve_hwnd(step, context)
        if not hwnd:
            return {**entry, "success": False, "error": "no window target"}
        ok = focus_safe_show(hwnd)
        return {**entry, "success": bool(ok), "hwnd": hwnd}

    if action == "click":
        find_by = step.get("find_by", "name")
        value = step.get("value", "")
        x = step.get("x")
        y = step.get("y")
        if value and _HAS_BG_PRIMS:
            res = uia_invoke_element(find_by, value)
            return {**entry, **res}
        if x is not None and y is not None:
            if _HAS_CUA and cua_available():
                try:
                    payload = {"x": int(x), "y": int(y)}
                    button = step.get("button")
                    if button:
                        payload["button"] = button
                    res = cua_call("click", payload)
                    return {**entry, "success": bool(res.get("ok")), "method": "cua_click", **res}
                except Exception as exc:
                    return {**entry, "success": False, "error": f"cua click failed: {exc}"}
            return {**entry, "success": False, "error": "no click backend available"}
        return {**entry, "success": False, "error": "need value or x/y"}

    if action == "type":
        text = step.get("text", "")
        if not text:
            return {**entry, "success": False, "error": "missing text"}
        hwnd = _resolve_hwnd(step, context)
        if hwnd and _HAS_BG_PRIMS:
            res = type_via_uia(hwnd, text)
            if not res.get("success"):
                res = type_into_window_post(hwnd, text, int(step.get("delay_ms", 10)))
            return {**entry, **res, "hwnd": hwnd}
        if _HAS_CUA and cua_available():
            try:
                res = cua_call("type_text", {"text": text})
                return {**entry, "success": bool(res.get("ok")), "method": "cua_type_text", **res}
            except Exception as exc:
                return {**entry, "success": False, "error": f"cua type failed: {exc}"}
        return {**entry, "success": False, "error": "no typing backend available"}

    if action == "wait":
        seconds = float(step.get("seconds", 1.0))
        # Wait in short chunks so a stop request is responsive.
        remaining = max(0.0, seconds)
        step_size = 0.1
        while remaining > 0 and not _STOP_EVENT.is_set():
            time.sleep(min(step_size, remaining))
            remaining -= step_size
        return {**entry, "success": True, "waited": seconds}

    if action == "cua":
        if not _HAS_CUA or not cua_available():
            return {**entry, "success": False, "error": "cua bridge unavailable"}
        tool = step.get("tool")
        if not tool:
            return {**entry, "success": False, "error": "missing cua tool name"}
        try:
            res = cua_call(str(tool), step.get("data") or {})
            return {**entry, "success": bool(res.get("ok")), "tool": tool, **res}
        except Exception as exc:
            return {**entry, "success": False, "error": f"cua call failed: {exc}"}

    return {**entry, "success": False, "error": f"unknown action: {action or '(empty)'}"}


def _worker_loop(run_id, task, steps, loop, loop_delay, step_delay):
    _console(f"[BG-AGENT] start run={run_id} task={task!r} steps={len(steps)} loop={loop}")
    iteration = 0
    try:
        while not _STOP_EVENT.is_set():
            iteration += 1
            context = {"hwnd": 0, "window": ""}
            for step in steps:
                if _STOP_EVENT.is_set():
                    break
                if not isinstance(step, dict):
                    _record_result({"type": "invalid", "success": False, "error": "step not an object"})
                    continue
                try:
                    result = _run_step(step, context)
                except Exception as exc:
                    result = {"type": step.get("type"), "success": False, "error": str(exc)}
                result["iteration"] = iteration
                _record_result(result)
                if step_delay > 0 and not _STOP_EVENT.is_set():
                    time.sleep(step_delay)
            if not loop:
                break
            if _STOP_EVENT.is_set():
                break
            if loop_delay > 0:
                # Chunked sleep so /bg/stop stays responsive.
                remaining = float(loop_delay)
                while remaining > 0 and not _STOP_EVENT.is_set():
                    slice_ = min(0.25, remaining)
                    time.sleep(slice_)
                    remaining -= slice_
        final = "stopped" if _STOP_EVENT.is_set() else "completed"
        _set_status(final, ended=True)
        _console(f"[BG-AGENT] {final} run={run_id} iterations={iteration}")
    except Exception as exc:
        _set_status("error", ended=True, error=str(exc))
        _log(f"[BG-AGENT] worker crashed: {exc}")


def _reset_state(run_id, task, steps_total):
    with _STATE_LOCK:
        _STATE["run_id"] = run_id
        _STATE["task"] = task
        _STATE["active"] = True
        _STATE["status"] = "running"
        _STATE["started_at"] = time.time()
        _STATE["ended_at"] = 0.0
        _STATE["steps_total"] = steps_total
        _STATE["steps_done"] = 0
        _STATE["last_action"] = ""
        _STATE["last_error"] = None
        _STATE["results"] = []


def register_routes(app, state, require_auth):

    @app.route("/bg/run", methods=["POST"])
    @require_auth
    def route_bg_run():
        body = _json_body() or {}
        task = str(body.get("task") or "background agent").strip()
        steps = body.get("steps") or body.get("actions") or []
        if not isinstance(steps, list) or not steps:
            return jsonify({"error": "steps must be a non-empty list"}), 400
        if len(steps) > _MAX_STEPS:
            return jsonify({"error": f"too many steps (max {_MAX_STEPS})"}), 400

        loop = bool(body.get("loop", False))
        try:
            loop_delay = max(0.0, float(body.get("loop_delay", 1.0)))
            step_delay = max(0.0, float(body.get("step_delay", 0.0)))
        except (TypeError, ValueError):
            return jsonify({"error": "loop_delay and step_delay must be numeric"}), 400

        with _STATE_LOCK:
            already = _STATE["active"]
        if already:
            return jsonify({
                "error": "a background agent task is already running",
                "run_id": _STATE["run_id"],
            }), 409

        run_id = uuid.uuid4().hex[:12]
        _STOP_EVENT.clear()
        _reset_state(run_id, task, len(steps))

        worker = threading.Thread(
            target=_worker_loop,
            args=(run_id, task, steps, loop, loop_delay, step_delay),
            name=f"bg-agent-{run_id}",
            daemon=True,
        )
        _WORKER["thread"] = worker
        worker.start()

        _log(f"bg/run started run={run_id} task={task!r} steps={len(steps)} loop={loop}")
        return jsonify({
            "status": "started",
            "run_id": run_id,
            "task": task,
            "steps_total": len(steps),
            "loop": loop,
            "focus_safe": True,
            "primitives": {
                "background": _HAS_BG_PRIMS,
                "cua": _HAS_CUA and cua_available(),
            },
        })

    @app.route("/bg/status", methods=["GET", "POST"])
    @require_auth
    def route_bg_status():
        snap = _snapshot_state()
        return jsonify(snap)

    @app.route("/bg/stop", methods=["POST"])
    @require_auth
    def route_bg_stop():
        with _STATE_LOCK:
            active = _STATE["active"]
            run_id = _STATE["run_id"]
        if not active:
            return jsonify({"status": "idle", "run_id": run_id, "stopped": False})
        _STOP_EVENT.set()
        _set_status("stopping")
        worker = _WORKER.get("thread")
        joined = False
        if worker and worker.is_alive():
            worker.join(timeout=2.0)
            joined = not worker.is_alive()
        _log(f"bg/stop signalled run={run_id} joined={joined}")
        return jsonify({
            "status": "stopping",
            "run_id": run_id,
            "stopped": True,
            "joined": joined,
        })
