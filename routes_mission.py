"""routes_mission.py — Autonomous Goal-to-Plan Executor

Accepts a natural language goal, breaks it into steps using a planning LLM,
executes each step via CoAgent's REST API, verifies results, and reports.

Endpoints:
  POST /mission/start  — Accept a goal, return mission_id + plan
  GET  /mission/status — Check progress of a running mission
  POST /mission/cancel — Cancel a running mission
  GET  /mission/log    — Full mission execution log

Usage (from any AI agent):
  curl -X POST http://127.0.0.1:9123/mission/start \\
    -H "Authorization: Bearer <token>" \\
    -H "Content-Type: application/json" \\
    -d '{"goal": "Open Notepad, type Hello World, save to desktop"}'
"""

import json, os, threading, time, traceback, uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, g

# ---------------------------------------------------------------------------
# Shared directory & SQLite for mission persistence
# ---------------------------------------------------------------------------
COAGENT_DIR = Path(__file__).parent.resolve()
MISSIONS_DB = COAGENT_DIR / "missions.db"
MISSIONS_DIR = COAGENT_DIR / "missions"
MISSIONS_DIR.mkdir(exist_ok=True)

try:
    import sqlite3

    def _init_db():
        con = sqlite3.connect(str(MISSIONS_DB))
        con.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                plan TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                completed_at TEXT,
                summary TEXT,
                log TEXT
            )
        """)
        con.commit()
        con.close()

    _init_db()
except ImportError:
    sqlite3 = None

# ---------------------------------------------------------------------------
# Active missions (in-memory state)
# ---------------------------------------------------------------------------
_ACTIVE_MISSIONS: dict = {}
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _log(mission_id: str, level: str, msg: str):
    ts = datetime.utcnow().isoformat()
    entry = {"ts": ts, "level": level, "msg": msg}
    with _LOCK:
        m = _ACTIVE_MISSIONS.get(mission_id)
        if m:
            m.get("log_entries", []).append(entry)
    return entry


def _call_coagent(endpoint: str, method: str = "GET", body: dict = None) -> dict:
    """Call an internal CoAgent endpoint using urllib."""
    import urllib.request, urllib.error

    url = f"http://127.0.0.1:9123{endpoint}"
    headers = {"Content-Type": "application/json"}
    # Propagate auth token from incoming request
    auth = request.headers.get("Authorization", "")
    if auth:
        headers["Authorization"] = auth

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _plan_steps(goal: str) -> list:
    """Use the local agent loop to break a goal into executable steps.

    Falls back to a simple regex-based planner if no LLM is available.
    Returns a list of step dicts: {action, params, description}
    """
    # Try the agent gateway first
    plan_prompt = (
        "You are a Windows desktop automation planner. Break this goal into "
        "atomic steps using ONLY these available tools:\n"
        "- mouse_click(x, y, button='left')\n"
        "- mouse_move(x, y)\n"
        "- key_type(text)\n"
        "- key_press(key)\n"
        "- key_hotkey(keys) - e.g. Ctrl+S, Alt+F4\n"
        "- process_start(path)\n"
        "- process_list()\n"
        "- window_activate(title)\n"
        "- window_list()\n"
        "- uia_click(name) - click element by UIA name\n"
        "- ocr_find(text) - find text on screen, return coords\n"
        "- screen_text() - OCR entire screen\n"
        "- clipboard_get()\n"
        "- clipboard_set(text)\n"
        "- wait(seconds)\n"
        "- screenshot()\n"
        "Return ONLY a JSON array of steps. Each step: {tool, params: {}, description: ''}\n"
        f"Goal: {goal}"
    )

    try:
        resp = _call_coagent(
            "/agent/exec",
            method="POST",
            body={"prompt": plan_prompt, "agent": "builtin"},
        )
        if resp.get("ok") and resp.get("output"):
            text = resp["output"]
            # Extract JSON array from response
            start = text.find("[")
            end = text.rfind("]")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
    except Exception:
        pass

    # Fallback: simple heuristic planners for common goals
    goal_lower = goal.lower()
    steps = []

    # Notepad workflow
    if "notepad" in goal_lower:
        steps.append({"tool": "process_start", "params": {"path": "notepad.exe"}, "description": "Launch Notepad"})
        steps.append({"tool": "wait", "params": {"seconds": 1}, "description": "Wait for Notepad to open"})
        if "type" in goal_lower or "hello" in goal_lower or "text" in goal_lower:
            text = "Hello World"
            for tag in ["type", "hello", "text", "write", "enter"]:
                idx = goal_lower.find(tag)
                if idx >= 0:
                    # Try to extract what follows
                    remainder = goal_lower[idx + len(tag) :].strip().strip('"').strip("'")
                    if remainder and len(remainder) < 100:
                        text = remainder
                        break
            steps.append({"tool": "key_type", "params": {"text": text}, "description": f"Type text: {text[:50]}"})
        if "save" in goal_lower:
            steps.append({"tool": "key_hotkey", "params": {"keys": ["Ctrl", "S"]}, "description": "Open Save dialog (Ctrl+S)"})
            steps.append({"tool": "wait", "params": {"seconds": 1}, "description": "Wait for save dialog"})
            if "desktop" in goal_lower:
                steps.append({"tool": "key_type", "params": {"text": "%USERPROFILE%\\Desktop\\untitled.txt\n"}, "description": "Save to desktop"})
                steps.append({"tool": "key_press", "params": {"key": "enter"}, "description": "Confirm save"})

    # Calculator
    elif "calculator" in goal_lower or "calc" in goal_lower:
        steps.append({"tool": "process_start", "params": {"path": "calc.exe"}, "description": "Launch Calculator"})
        steps.append({"tool": "wait", "params": {"seconds": 1.5}, "description": "Wait for Calculator"})

    # Browser
    elif "browser" in goal_lower or "chrome" in goal_lower or "edge" in goal_lower or "open" in goal_lower:
        steps.append({"tool": "process_start", "params": {"path": "msedge.exe"}, "description": "Launch Edge browser"})
        steps.append({"tool": "wait", "params": {"seconds": 2}, "description": "Wait for browser"})

    # Screenshot
    elif "screenshot" in goal_lower or "capture" in goal_lower:
        steps.append({"tool": "screenshot", "params": {}, "description": "Take a screenshot"})

    # Generic fallback
    if not steps:
        steps.append({"tool": "screen_text", "params": {}, "description": "Read what's on screen"})
        steps.append({"tool": "window_list", "params": {}, "description": "List open windows"})

    return steps


def _execute_step(step: dict, mission_id: str) -> dict:
    """Execute a single step and return the result."""
    tool = step.get("tool", "")
    params = step.get("params", {})

    _log(mission_id, "info", f"Executing: {step.get('description', tool)}")

    # Map tools to CoAgent endpoints
    tool_map = {
        "mouse_click": ("POST", "/mouse/click", ["x", "y", "button"]),
        "mouse_move": ("POST", "/mouse/move", ["x", "y"]),
        "key_type": ("POST", "/key/type", ["text"]),
        "key_press": ("POST", "/key/press", ["key"]),
        "key_hotkey": ("POST", "/key/hotkey", ["keys"]),
        "process_start": ("POST", "/process/start", ["path"]),
        "process_list": ("GET", "/process/list", None),
        "window_activate": ("POST", "/media/window/activate", ["title"]),
        "window_list": ("GET", "/media/window/list", None),
        "uia_click": ("POST", "/uia/click", ["name"]),
        "ocr_find": ("POST", "/ocr/find", ["text"]),
        "screen_text": ("GET", "/ocr/screen", None),
        "clipboard_get": ("GET", "/media/clipboard/get", None),
        "clipboard_set": ("POST", "/media/clipboard/set", ["text"]),
        "wait": ("WAIT", None, ["seconds"]),
        "screenshot": ("GET", "/screen/base64", None),
    }

    if tool not in tool_map:
        return {"ok": False, "error": f"Unknown tool: {tool}"}

    method, endpoint, param_keys = tool_map[tool]

    if tool == "wait":
        secs = float(params.get("seconds", 1))
        time.sleep(secs)
        return {"ok": True, "output": f"Waited {secs}s"}

    body = {}
    if param_keys:
        for k in param_keys:
            if k in params:
                body[k] = params[k]

    result = _call_coagent(endpoint, method=method, body=body if param_keys else None)
    return result


def _run_mission(mission_id: str, goal: str, steps: list):
    """Execute mission steps in a background thread."""
    try:
        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if m:
                m["status"] = "running"
                m["current_step"] = 0
                m["total_steps"] = len(steps)

        _log(mission_id, "info", f"Mission started: {goal}")
        _log(mission_id, "info", f"Plan: {len(steps)} steps")

        for idx, step in enumerate(steps):
            with _LOCK:
                m = _ACTIVE_MISSIONS.get(mission_id)
                if m and m["status"] == "cancelled":
                    _log(mission_id, "warn", "Mission cancelled by user")
                    return
                if m:
                    m["current_step"] = idx

            desc = step.get("description", step.get("tool", f"step {idx}"))
            result = _execute_step(step, mission_id)

            if not result.get("ok", False):
                _log(mission_id, "error", f"Step {idx} ({desc}) failed: {result.get('error', 'unknown')}")
                with _LOCK:
                    m = _ACTIVE_MISSIONS.get(mission_id)
                    if m:
                        m["status"] = "failed"
                        m["error_step"] = idx
                        m["error_msg"] = result.get("error", "Unknown error")
                return

            _log(mission_id, "success", f"Step {idx} ({desc}) completed")

        # All steps completed
        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if m:
                m["status"] = "completed"
                m["completed_at"] = datetime.utcnow().isoformat()
                m["summary"] = f"All {len(steps)} steps completed successfully"

        _log(mission_id, "success", f"Mission completed: {len(steps)}/{len(steps)} steps")

        # Persist to DB
        _persist_mission(mission_id)

    except Exception as e:
        _log(mission_id, "error", f"Mission crashed: {traceback.format_exc()}")
        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if m:
                m["status"] = "error"
                m["error_msg"] = str(e)


def _persist_mission(mission_id: str):
    """Save mission to SQLite."""
    if not sqlite3:
        return
    try:
        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id, {})
        con = sqlite3.connect(str(MISSIONS_DB))
        log_text = json.dumps(m.get("log_entries", []))
        con.execute(
            "INSERT OR REPLACE INTO missions (id, goal, plan, status, created_at, completed_at, summary, log) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                mission_id,
                m.get("goal", ""),
                json.dumps(m.get("steps", [])),
                m.get("status", "unknown"),
                m.get("created_at", ""),
                m.get("completed_at", ""),
                m.get("summary", ""),
                log_text,
            ),
        )
        con.commit()
        con.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):
    @app.route("/mission/start", methods=["POST"])
    @require_auth
    def mission_start():
        """Start an autonomous mission from a natural language goal."""
        data = request.get_json(silent=True) or {}
        goal = data.get("goal", "").strip()
        if not goal:
            return jsonify({"ok": False, "error": "Missing 'goal'"}), 400

        mission_id = uuid.uuid4().hex[:12]
        steps = data.get("steps")  # optional: caller provides steps directly
        if not steps:
            steps = _plan_steps(goal)

        now = datetime.utcnow().isoformat()
        with _LOCK:
            _ACTIVE_MISSIONS[mission_id] = {
                "id": mission_id,
                "goal": goal,
                "steps": steps,
                "status": "planning",
                "created_at": now,
                "completed_at": None,
                "summary": None,
                "current_step": 0,
                "total_steps": len(steps),
                "log_entries": [],
            }

        # Launch executor in background thread
        t = threading.Thread(target=_run_mission, args=(mission_id, goal, steps), daemon=True)
        t.start()

        return jsonify({
            "ok": True,
            "mission_id": mission_id,
            "goal": goal,
            "steps": [
                {"tool": s["tool"], "description": s.get("description", "")}
                for s in steps
            ],
            "total_steps": len(steps),
        })

    @app.route("/mission/status", methods=["GET"])
    def mission_status():
        """Get the current status of a running/completed mission."""
        mission_id = request.args.get("id", "")
        if not mission_id:
            return jsonify({"ok": False, "error": "Missing 'id' parameter"}), 400

        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if not m:
                # Try DB
                if sqlite3:
                    try:
                        con = sqlite3.connect(str(MISSIONS_DB))
                        row = con.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
                        con.close()
                        if row:
                            cols = ["id", "goal", "plan", "status", "created_at", "completed_at", "summary", "log"]
                            return jsonify(dict(zip(cols, row)))
                    except Exception:
                        pass
                return jsonify({"ok": False, "error": "Mission not found"}), 404

        return jsonify({
            "ok": True,
            "mission_id": m["id"],
            "goal": m["goal"],
            "status": m["status"],
            "current_step": m.get("current_step", 0),
            "total_steps": m.get("total_steps", 0),
            "created_at": m.get("created_at"),
            "completed_at": m.get("completed_at"),
            "summary": m.get("summary"),
            "error_msg": m.get("error_msg"),
        })

    @app.route("/mission/cancel", methods=["POST"])
    @require_auth
    def mission_cancel():
        """Cancel a running mission."""
        data = request.get_json(silent=True) or {}
        mission_id = data.get("id", "")

        if not mission_id:
            return jsonify({"ok": False, "error": "Missing 'id'"}), 400

        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if not m:
                return jsonify({"ok": False, "error": "Mission not found"}), 404
            m["status"] = "cancelled"

        return jsonify({"ok": True, "mission_id": mission_id, "status": "cancelled"})

    @app.route("/mission/log", methods=["GET"])
    def mission_log():
        """Get the full execution log for a mission."""
        mission_id = request.args.get("id", "")
        if not mission_id:
            return jsonify({"ok": False, "error": "Missing 'id' parameter"}), 400

        with _LOCK:
            m = _ACTIVE_MISSIONS.get(mission_id)
            if not m:
                return jsonify({"ok": False, "error": "Mission not found"}), 404
            entries = list(m.get("log_entries", []))

        return jsonify({
            "ok": True,
            "mission_id": mission_id,
            "entries": entries,
            "count": len(entries),
        })

    @app.route("/mission/list", methods=["GET"])
    def mission_list():
        """List all missions (from memory + DB)."""
        with _LOCK:
            active = [
                {"id": m["id"], "goal": m["goal"][:80], "status": m["status"],
                 "created_at": m.get("created_at"), "steps": m.get("total_steps", 0)}
                for m in _ACTIVE_MISSIONS.values()
            ]

        historic = []
        if sqlite3:
            try:
                con = sqlite3.connect(str(MISSIONS_DB))
                rows = con.execute(
                    "SELECT id, goal, status, created_at, completed_at FROM missions ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
                con.close()
                for r in rows:
                    historic.append({
                        "id": r[0], "goal": r[1][:80] if r[1] else "", "status": r[2],
                        "created_at": r[3], "completed_at": r[4],
                    })
            except Exception:
                pass

        return jsonify({
            "ok": True,
            "active": active,
            "historic": historic,
        })
