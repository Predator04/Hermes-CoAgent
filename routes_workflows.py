"""No-code visual workflow builder.

Persists node-graph workflows in COAGENT_DIR/workflows/*.json and compiles
them down to recipe JSON that is executed by routes_recipes.py — so the
execution engine, logging and SSE progress are reused unchanged.
"""

import json
import re
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _json_body, _wrap_registered_blueprint_routes

try:
    from routes_recipes import (
        _coagent_request,
        _execute_steps,
        _auth_header,
        _normalize_recipe,
    )
    HAS_RECIPES_ENGINE = True
except Exception as exc:
    HAS_RECIPES_ENGINE = False
    _console(f"[workflows] recipes engine unavailable: {type(exc).__name__}: {exc}")

    def _coagent_request(*_a, **_kw):
        return {"error": "recipes engine unavailable", "status_code": 0}

    def _execute_steps(steps, timeout=300, auth_header=None):
        return [{"step_index": 0, "action": "unknown", "status": "error",
                 "error": "recipes engine unavailable"}]

    def _auth_header(preferred=None):
        try:
            return request.headers.get("Authorization", "") if preferred is None else preferred
        except RuntimeError:
            return preferred or ""

    def _normalize_recipe(data, recipe_id=None):
        raise ValueError("recipes engine unavailable")


workflows_bp = Blueprint("workflows", __name__)

WORKFLOWS_DIR = COAGENT_DIR / "workflows"
_WORKFLOWS_LOCK = threading.RLock()

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _ensure_dir():
    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _console(f"[workflows] cannot create {WORKFLOWS_DIR}: {exc}")


def _safe_id(workflow_id):
    wid = str(workflow_id or "").strip()
    if not _ID_RE.match(wid):
        raise ValueError("invalid workflow id")
    return wid


def _workflow_path(workflow_id):
    return WORKFLOWS_DIR / f"{_safe_id(workflow_id)}.json"


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- schema/normalize

def _normalize_workflow(data, workflow_id=None):
    if not isinstance(data, dict):
        raise ValueError("workflow must be an object")
    wid = workflow_id or data.get("id") or data.get("workflow_id") or uuid.uuid4().hex[:16]
    wid = _safe_id(wid)
    name = str(data.get("name") or "").strip() or f"Workflow {wid[:6]}"
    description = str(data.get("description") or "").strip()
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list):
        raise ValueError("nodes must be a list")
    if not isinstance(edges, list):
        edges = []
    normalized_nodes = []
    seen_ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("each node must be an object")
        node_id = str(node.get("id") or "").strip() or uuid.uuid4().hex[:12]
        if node_id in seen_ids:
            raise ValueError(f"duplicate node id: {node_id}")
        seen_ids.add(node_id)
        node_type = str(node.get("type") or "").strip()
        if not node_type:
            raise ValueError("node type is required")
        position = node.get("position") if isinstance(node.get("position"), dict) else {"x": 40, "y": 40}
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        normalized_nodes.append({
            "id": node_id,
            "type": node_type,
            "label": str(node.get("label") or "").strip(),
            "position": {
                "x": int(position.get("x", 40) or 0),
                "y": int(position.get("y", 40) or 0),
            },
            "params": params,
        })
    normalized_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target or source not in seen_ids or target not in seen_ids:
            continue
        normalized_edges.append({
            "id": str(edge.get("id") or "").strip() or uuid.uuid4().hex[:12],
            "source": source,
            "target": target,
            "label": str(edge.get("label") or "").strip(),
        })
    return {
        "id": wid,
        "name": name,
        "description": description,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "created_at": data.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
    }


# ---------------------------------------------------------------- graph → recipe

_SIMPLE_ACTIONS = {
    "action.wait": ("wait", ["seconds"]),
    "action.launch": ("launch", ["query", "path", "app", "command"]),
    "action.click": ("click", ["x", "y", "text", "button"]),
    "action.type": ("type", ["text"]),
    "action.key": ("key", ["keys"]),
    "action.hotkey": ("hotkey", ["keys"]),
    "action.screenshot": ("screenshot", []),
    "action.ocr_find": ("ocr_find", ["text", "region"]),
    "action.telegram_send": ("telegram_send", ["message", "text", "chat_id"]),
    "action.finder_click": ("finder_click", ["query", "text"]),
    "action.finder_type": ("finder_type", ["query", "text"]),
}


_MAX_COMPILED_STEPS = 5000


def _params_only(params, allowed):
    if not allowed:
        return {}
    return {k: params[k] for k in allowed if k in params and params[k] not in (None, "")}


def _compile_workflow(workflow):
    """Compile a workflow graph into a recipe dict (name, steps, schedule)."""
    nodes = {node["id"]: node for node in workflow.get("nodes", [])}
    edges = workflow.get("edges", [])
    successors = {nid: [] for nid in nodes}
    indegree = {nid: 0 for nid in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in successors and target in indegree:
            successors[source].append(target)
            indegree[target] += 1

    trigger_nodes = [n for n in nodes.values() if n["type"].startswith("trigger.")]
    if trigger_nodes:
        start_id = trigger_nodes[0]["id"]
    else:
        roots = [nid for nid, deg in indegree.items() if deg == 0]
        if not roots:
            raise ValueError("workflow has no entry node (need a trigger or root)")
        start_id = roots[0]

    schedule = ""
    trigger_meta = {}
    if trigger_nodes:
        trig = trigger_nodes[0]
        ttype = trig["type"]
        params = trig.get("params") or {}
        if ttype == "trigger.schedule":
            schedule = str(params.get("schedule") or params.get("cron") or "").strip()
        elif ttype == "trigger.webhook":
            trigger_meta = {"webhook": params.get("name") or trig["id"]}
        elif ttype == "trigger.file_watch":
            trigger_meta = {"file_watch": params.get("path") or ""}
        elif ttype == "trigger.window_open":
            trigger_meta = {"window_open": params.get("title") or ""}
        elif ttype == "trigger.notification":
            trigger_meta = {"notification": params.get("keyword") or ""}

    steps = []
    visited = set()

    def walk(node_id):
        if len(steps) > _MAX_COMPILED_STEPS:
            raise ValueError(f"workflow expands beyond {_MAX_COMPILED_STEPS} steps (nested loops too deep)")
        if node_id in visited or node_id not in nodes:
            return
        visited.add(node_id)
        node = nodes[node_id]
        ntype = node["type"]
        params = node.get("params") or {}

        if ntype.startswith("action."):
            mapping = _SIMPLE_ACTIONS.get(ntype)
            if mapping:
                action, allowed = mapping
                step = {"action": action, "params": _params_only(params, allowed)}
                steps.append(step)
            else:
                custom_action = params.get("action")
                if custom_action:
                    steps.append({"action": str(custom_action).strip(), "params": dict(params)})
        elif ntype == "condition.wait_for":
            text = params.get("text") or ""
            if text:
                steps.append({"action": "ocr_find", "params": {"text": text}})
        elif ntype == "loop.repeat":
            count = max(1, min(int(params.get("count", 1) or 1), 50))
            body_ids = successors.get(node_id, [])
            body_snapshot_start = len(steps)
            for child_id in body_ids:
                if child_id not in visited:
                    walk(child_id)
            body = list(steps[body_snapshot_start:])
            del steps[body_snapshot_start:]
            for _ in range(count):
                for step in body:
                    steps.append(deepcopy(step))
                    if len(steps) > _MAX_COMPILED_STEPS:
                        raise ValueError(
                            f"workflow expands beyond {_MAX_COMPILED_STEPS} steps (nested loops too deep)"
                        )
            return

        for child_id in successors.get(node_id, []):
            walk(child_id)

    walk(start_id)

    if not steps:
        steps.append({"action": "wait", "params": {"seconds": 0}})

    recipe = {
        "name": workflow.get("name") or f"Workflow {workflow.get('id', '')[:6]}",
        "steps": steps,
        "schedule": schedule,
        "enabled": True,
    }
    if trigger_meta:
        recipe["trigger"] = trigger_meta
    return recipe


# ---------------------------------------------------------------- persistence

def _load_workflow(workflow_id):
    path = _workflow_path(workflow_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _console(f"[workflows] cannot read {path}: {exc}")
        return None


def _list_workflows():
    _ensure_dir()
    items = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "id": data.get("id") or path.stem,
                "name": data.get("name") or path.stem,
                "description": data.get("description", ""),
                "node_count": len(data.get("nodes", [])),
                "edge_count": len(data.get("edges", [])),
                "updated_at": data.get("updated_at"),
                "created_at": data.get("created_at"),
            })
        except Exception as exc:
            _console(f"[workflows] skipping {path.name}: {exc}")
    return items


def _save_workflow(workflow):
    _ensure_dir()
    path = _workflow_path(workflow["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(workflow, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- templates

def _templates():
    return [
        {
            "id": "hello-telegram",
            "name": "Hello via Telegram",
            "description": "Send a Telegram message once, on demand.",
            "nodes": [
                {"id": "t1", "type": "trigger.manual", "label": "Run manually",
                 "position": {"x": 60, "y": 80}, "params": {}},
                {"id": "a1", "type": "action.telegram_send", "label": "Send hello",
                 "position": {"x": 320, "y": 80},
                 "params": {"message": "Hello from Hermes CoAgent"}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
        },
        {
            "id": "screenshot-every-hour",
            "name": "Hourly Screenshot",
            "description": "Take a screenshot at the top of every hour.",
            "nodes": [
                {"id": "t1", "type": "trigger.schedule", "label": "Hourly",
                 "position": {"x": 60, "y": 80}, "params": {"schedule": "hourly"}},
                {"id": "a1", "type": "action.screenshot", "label": "Capture screen",
                 "position": {"x": 320, "y": 80}, "params": {}},
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
        },
        {
            "id": "open-notepad-type",
            "name": "Open Notepad and Type",
            "description": "Launch Notepad, wait a moment, then type a note.",
            "nodes": [
                {"id": "t1", "type": "trigger.manual", "label": "Run manually",
                 "position": {"x": 40, "y": 80}, "params": {}},
                {"id": "a1", "type": "action.launch", "label": "Launch Notepad",
                 "position": {"x": 260, "y": 80}, "params": {"query": "notepad"}},
                {"id": "a2", "type": "action.wait", "label": "Wait 2s",
                 "position": {"x": 480, "y": 80}, "params": {"seconds": 2}},
                {"id": "a3", "type": "action.type", "label": "Type text",
                 "position": {"x": 700, "y": 80},
                 "params": {"text": "Hello from CoAgent workflow"}},
            ],
            "edges": [
                {"id": "e1", "source": "t1", "target": "a1"},
                {"id": "e2", "source": "a1", "target": "a2"},
                {"id": "e3", "source": "a2", "target": "a3"},
            ],
        },
    ]


# ---------------------------------------------------------------- routes

@workflows_bp.route("/workflows", methods=["GET"])
def route_workflows_list():
    with _WORKFLOWS_LOCK:
        items = _list_workflows()
    items.sort(key=lambda item: (item.get("name") or "").lower())
    return jsonify({"workflows": items, "count": len(items), "dir": str(WORKFLOWS_DIR)})


@workflows_bp.route("/workflows", methods=["POST"])
def route_workflows_save():
    data = _json_body()
    try:
        workflow = _normalize_workflow(data, workflow_id=data.get("id") or data.get("workflow_id"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _WORKFLOWS_LOCK:
        existing = _load_workflow(workflow["id"])
        if existing and isinstance(existing, dict):
            workflow["created_at"] = existing.get("created_at") or workflow["created_at"]
        _save_workflow(workflow)
    return jsonify({"id": workflow["id"], "name": workflow["name"],
                    "node_count": len(workflow["nodes"]),
                    "edge_count": len(workflow["edges"]),
                    "updated_at": workflow["updated_at"]})


@workflows_bp.route("/workflows/templates", methods=["GET"])
def route_workflows_templates():
    templates = _templates()
    return jsonify({"templates": templates, "count": len(templates)})


@workflows_bp.route("/workflows/<workflow_id>", methods=["GET"])
def route_workflows_get(workflow_id):
    try:
        _safe_id(workflow_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _WORKFLOWS_LOCK:
        workflow = _load_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "workflow not found", "id": workflow_id}), 404
    return jsonify(workflow)


@workflows_bp.route("/workflows/<workflow_id>", methods=["DELETE"])
def route_workflows_delete(workflow_id):
    try:
        path = _workflow_path(workflow_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _WORKFLOWS_LOCK:
        if not path.exists():
            return jsonify({"error": "workflow not found", "id": workflow_id}), 404
        try:
            path.unlink()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500
    return jsonify({"status": "deleted", "id": workflow_id})


@workflows_bp.route("/workflows/<workflow_id>/compile", methods=["POST"])
def route_workflows_compile(workflow_id):
    try:
        _safe_id(workflow_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _WORKFLOWS_LOCK:
        workflow = _load_workflow(workflow_id)
    if not workflow:
        data = _json_body()
        if isinstance(data, dict) and (data.get("nodes") or data.get("workflow")):
            try:
                workflow = _normalize_workflow(data.get("workflow") if isinstance(data.get("workflow"), dict) else data, workflow_id=workflow_id)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        else:
            return jsonify({"error": "workflow not found", "id": workflow_id}), 404
    try:
        recipe = _compile_workflow(workflow)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": workflow.get("id"), "recipe": recipe})


@workflows_bp.route("/workflows/<workflow_id>/run", methods=["POST"])
def route_workflows_run(workflow_id):
    try:
        _safe_id(workflow_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with _WORKFLOWS_LOCK:
        workflow = _load_workflow(workflow_id)
    if not workflow:
        return jsonify({"error": "workflow not found", "id": workflow_id}), 404
    try:
        recipe = _compile_workflow(workflow)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    steps = recipe.get("steps", [])
    if not steps:
        return jsonify({"error": "workflow compiled to zero steps"}), 400
    auth = _auth_header(request.headers.get("Authorization", ""))
    result = _coagent_request("POST", "/recipes/run",
                              {"steps": steps, "timeout": 300},
                              auth_header=auth, timeout=310)
    status_code = 200
    if isinstance(result, dict):
        status_code = int(result.pop("status_code", 200) or 200)
    return jsonify({"id": workflow.get("id"), "recipe": recipe, "run": result}), status_code


def register_routes(app, state, require_auth):
    _ensure_dir()
    app.register_blueprint(workflows_bp)
    _wrap_registered_blueprint_routes(app, workflows_bp.name, require_auth)
    state.workflows = {"dir": str(WORKFLOWS_DIR), "recipes_engine": HAS_RECIPES_ENGINE}
