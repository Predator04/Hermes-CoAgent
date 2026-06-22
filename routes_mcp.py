"""Native MCP JSON-RPC bridge for Hermes routes."""

import json
import queue
import re
import threading
import time

from flask import Response, jsonify, request, stream_with_context

from shared import AGENT_NAME, VERSION


_SUBSCRIBERS = []
_SUBSCRIBERS_LOCK = threading.Lock()


def _json_payload():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id, code, message, data=None):
    payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _broadcast(event, data):
    message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with _SUBSCRIBERS_LOCK:
        dead = []
        for sub in _SUBSCRIBERS:
            try:
                sub.put_nowait(message)
            except Exception:
                dead.append(sub)
        for sub in dead:
            if sub in _SUBSCRIBERS:
                _SUBSCRIBERS.remove(sub)


def _path_template(rule):
    return re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule)


def _tool_base_name(method, path):
    name = path.strip("/") or "root"
    name = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"by_\1", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "root"
    if method not in {"GET", "POST"}:
        name = f"{method.lower()}_{name}"
    return name


def _route_table(app):
    used = {}
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.rule in {"/mcp", "/mcp/events"}:
            continue
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        for method in methods:
            base = _tool_base_name(method, rule.rule)
            name = base
            if name in used:
                name = f"{method.lower()}_{base}"
            counter = 2
            while name in used:
                name = f"{method.lower()}_{base}_{counter}"
                counter += 1
            used[name] = True
            rows.append({"name": name, "method": method, "rule": rule, "path": rule.rule})
    return rows


def _tool_schema(row):
    properties = {}
    required = []
    for arg in sorted(row["rule"].arguments):
        properties[arg] = {"type": "string", "description": f"Path parameter for {arg}"}
        required.append(arg)
    properties["_query"] = {"type": "object", "description": "Optional query string parameters"}
    properties["_headers"] = {"type": "object", "description": "Optional additional HTTP headers"}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def _tools_list(app):
    tools = []
    for row in _route_table(app):
        tools.append({
            "name": row["name"],
            "description": f"{row['method']} {_path_template(row['rule'])}",
            "inputSchema": _tool_schema(row),
            "annotations": {"method": row["method"], "path": row["path"]},
        })
    return tools


def _find_tool(app, name):
    for row in _route_table(app):
        if row["name"] == name:
            return row
    return None


def _fill_path(rule, args):
    path = rule.rule
    consumed = set()
    for arg in sorted(rule.arguments):
        if arg not in args:
            raise KeyError(arg)
        value = str(args[arg])
        consumed.add(arg)
        path = re.sub(r"<(?:[^:<>]+:)?" + re.escape(arg) + r">", value, path)
    return path, consumed


def _response_payload(resp):
    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return resp.get_json(silent=True)
    text = resp.get_data(as_text=True, errors="replace")
    if len(text) > 20000:
        text = text[:20000] + "\n[truncated]"
    return text


def _call_tool(app, params):
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return {"isError": True, "content": [{"type": "text", "text": "tool name is required"}]}
    if not isinstance(args, dict):
        return {"isError": True, "content": [{"type": "text", "text": "arguments must be an object"}]}
    row = _find_tool(app, name)
    if not row:
        return {"isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}
    try:
        path, consumed = _fill_path(row["rule"], args)
    except KeyError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"missing path argument: {e.args[0]}"}]}
    method = row["method"]
    headers = {}
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        headers["Authorization"] = auth_header
    extra_headers = args.get("_headers")
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    query = args.get("_query") if isinstance(args.get("_query"), dict) else {}
    body = {k: v for k, v in args.items() if k not in consumed and not k.startswith("_")}
    with app.test_client() as client:
        if method == "GET":
            resp = client.get(path, query_string=query or body, headers=headers)
        elif method == "POST":
            resp = client.post(path, json=body, query_string=query, headers=headers)
        elif method == "DELETE":
            resp = client.delete(path, json=body, query_string=query, headers=headers)
        elif method == "PUT":
            resp = client.put(path, json=body, query_string=query, headers=headers)
        elif method == "PATCH":
            resp = client.patch(path, json=body, query_string=query, headers=headers)
        else:
            return {"isError": True, "content": [{"type": "text", "text": f"unsupported method: {method}"}]}
    payload = {
        "status_code": resp.status_code,
        "headers": {"content-type": resp.headers.get("Content-Type", "")},
        "body": _response_payload(resp),
    }
    return {
        "isError": resp.status_code >= 400,
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
    }


def _handle_rpc(app, message):
    if not isinstance(message, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method == "initialize":
        _broadcast("initialized", {"time": time.time(), "client": params})
        return _jsonrpc_result(request_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": AGENT_NAME, "version": VERSION},
            "capabilities": {"tools": {}, "notifications": {}},
        })
    if method == "notifications/initialized":
        _broadcast("initialized", {"time": time.time()})
        return _jsonrpc_result(request_id, {})
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": _tools_list(app)})
    if method == "tools/call":
        result = _call_tool(app, params)
        _broadcast("tool_call", {"time": time.time(), "name": params.get("name"), "isError": result.get("isError")})
        return _jsonrpc_result(request_id, result)
    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def register_routes(app, state, require_auth):
    @app.route("/mcp", methods=["POST"])
    @require_auth
    def route_mcp_jsonrpc():
        payload = request.get_json(force=True, silent=True)
        if isinstance(payload, list):
            return jsonify([_handle_rpc(app, item) for item in payload])
        return jsonify(_handle_rpc(app, payload))

    @app.route("/mcp/events", methods=["GET"])
    @require_auth
    def route_mcp_events():
        def generate():
            q = queue.Queue(maxsize=100)
            with _SUBSCRIBERS_LOCK:
                _SUBSCRIBERS.append(q)
            try:
                yield f"event: ready\ndata: {json.dumps({'server': AGENT_NAME, 'version': VERSION})}\n\n"
                while True:
                    try:
                        yield q.get(timeout=30)
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                with _SUBSCRIBERS_LOCK:
                    if q in _SUBSCRIBERS:
                        _SUBSCRIBERS.remove(q)
        return Response(stream_with_context(generate()), mimetype="text/event-stream")

    @app.route("/mcp/tools", methods=["GET"])
    @require_auth
    def route_mcp_tools():
        return jsonify({"tools": _tools_list(app), "count": len(_tools_list(app))})
