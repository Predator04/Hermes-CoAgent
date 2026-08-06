"""MCP JSON-RPC bridge for Hermes CoAgent routes."""

import base64
import json
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Response, g, has_request_context, jsonify, request, stream_with_context

from shared import AGENT_NAME, BUILD, VERSION


MCP_PROTOCOL_VERSION = "2025-06-18"

_MAX_SSE_SUBSCRIBERS = 32

_SUBSCRIBERS = []
_SUBSCRIBERS_LOCK = threading.Lock()

_EXCLUDED_PATHS = {
    "/mcp",
    "/mcp/events",
    "/mcp/sse",
    "/mcp/message",
    "/mcp/tools",
}
_EXCLUDED_ENDPOINTS = {"static"}

_COMMON_SCHEMAS = {
    ("POST", "/mouse/move"): (
        {
            "x": {"type": "number", "description": "Target screen X coordinate"},
            "y": {"type": "number", "description": "Target screen Y coordinate"},
            "duration": {"type": "number", "description": "Optional move duration in seconds"},
        },
        ["x", "y"],
    ),
    ("POST", "/mouse/click"): (
        {
            "x": {"type": "number", "description": "Optional screen X coordinate"},
            "y": {"type": "number", "description": "Optional screen Y coordinate"},
            "button": {"type": "string", "description": "Mouse button: left, right, or middle"},
        },
        [],
    ),
    ("POST", "/mouse/drag"): (
        {
            "x1": {"type": "number", "description": "Start X coordinate"},
            "y1": {"type": "number", "description": "Start Y coordinate"},
            "x2": {"type": "number", "description": "End X coordinate"},
            "y2": {"type": "number", "description": "End Y coordinate"},
            "duration": {"type": "number", "description": "Optional drag duration in seconds"},
        },
        ["x1", "y1", "x2", "y2"],
    ),
    ("POST", "/mouse/scroll"): (
        {"amount": {"type": "integer", "description": "Scroll amount; positive up, negative down"}},
        ["amount"],
    ),
    ("POST", "/key/type"): (
        {"text": {"type": "string", "description": "Text to type"}},
        ["text"],
    ),
    ("POST", "/key/press"): (
        {"key": {"type": "string", "description": "Key or key combination to press"}},
        ["key"],
    ),
    ("POST", "/ocr/find"): (
        {
            "text": {"type": "string", "description": "Text to find on screen"},
            "monitor": {"type": "integer", "description": "Optional monitor index"},
        },
        ["text"],
    ),
    ("POST", "/file/list"): (
        {"path": {"type": "string", "description": "Directory path to list"}},
        [],
    ),
    ("POST", "/file/read"): (
        {"path": {"type": "string", "description": "File path to read"}},
        ["path"],
    ),
    ("POST", "/file/write"): (
        {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "UTF-8 text content"},
        },
        ["path"],
    ),
    ("POST", "/file/delete"): (
        {
            "path": {"type": "string", "description": "File or directory path to delete"},
            "confirm": {"type": "boolean", "description": "Required true for directory deletion"},
        },
        ["path"],
    ),
    ("POST", "/process/start"): (
        {
            "command": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Command to start",
            },
            "cwd": {"type": "string", "description": "Optional working directory"},
        },
        [],
    ),
    ("POST", "/process/kill"): (
        {
            "pid": {"type": "integer", "description": "Process ID"},
            "name": {"type": "string", "description": "Process image name"},
            "confirm": {"type": "boolean", "description": "Required confirmation"},
        },
        ["confirm"],
    ),
    ("POST", "/browser/dom"): (
        {
            "url": {"type": "string", "description": "URL to open and extract"},
            "headless": {"type": "boolean", "description": "Run browser headlessly"},
            "timeout": {"type": "integer", "description": "Navigation timeout in milliseconds"},
        },
        ["url"],
    ),
    ("POST", "/browser/dom-snapshot"): (
        {
            "url": {"type": "string", "description": "URL to open and inspect"},
            "headless": {"type": "boolean", "description": "Run browser headlessly"},
            "limit": {"type": "integer", "description": "Maximum interactive elements to return"},
        },
        ["url"],
    ),
    ("POST", "/memory/fact"): (
        {
            "key": {"type": "string", "description": "Fact key"},
            "value": {"description": "Fact value; stored as text or JSON"},
            "tags": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Tags stored as comma-separated text",
            },
            "source": {"type": "string", "description": "Optional source label"},
        },
        ["key", "value"],
    ),
    ("POST", "/memory/note"): (
        {
            "content": {"type": "string", "description": "Free-form note content"},
            "tags": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                "description": "Tags stored as comma-separated text",
            },
        },
        ["content"],
    ),
}

_PATH_NAME_ALIASES = {
    "/screen": "screen_capture",
    "/screen/base64": "screen_capture_base64",
    "/screen/jpeg": "screen_capture_jpeg",
    "/screen/fresh": "screen_capture_fresh",
    "/uia/tree": "uia_tree",
    "/uia/snapshot": "uia_snapshot",
    "/file/list": "file_list",
    "/process/list": "process_list",
    "/ocr/find": "ocr_find",
    "/copilot/observe": "copilot_observe",
}


def _jsonrpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id, code, message, data=None):
    payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _broadcast(event, data):
    message = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
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


def _converter_schema(rule, arg):
    converter = rule._converters.get(arg)
    converter_name = converter.__class__.__name__ if converter is not None else ""
    if converter_name in {"IntegerConverter"}:
        return {"type": "integer", "description": f"Path parameter for {arg}"}
    if converter_name in {"FloatConverter"}:
        return {"type": "number", "description": f"Path parameter for {arg}"}
    if converter_name in {"UUIDConverter"}:
        return {"type": "string", "format": "uuid", "description": f"Path parameter for {arg}"}
    return {"type": "string", "description": f"Path parameter for {arg}"}


def _convert_path_arg(rule, arg, value):
    converter = rule._converters.get(arg)
    converter_name = converter.__class__.__name__ if converter is not None else ""
    if converter_name == "IntegerConverter":
        return int(value)
    if converter_name == "FloatConverter":
        return float(value)
    return str(value)


def _tool_base_name(method, path):
    if path in _PATH_NAME_ALIASES:
        base = _PATH_NAME_ALIASES[path]
    else:
        base = path.strip("/") or "root"
        base = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"by_\1", base)
        base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower() or "root"
    name = f"coagent_{base}"
    if method not in {"GET", "POST"}:
        name = f"{name}_{method.lower()}"
    return name


def _route_table(app):
    used = {}
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        if rule.rule in _EXCLUDED_PATHS or rule.endpoint in _EXCLUDED_ENDPOINTS:
            continue
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        for method in methods:
            base = _tool_base_name(method, rule.rule)
            name = base
            if name in used:
                name = f"{base}_{method.lower()}"
            counter = 2
            while name in used:
                name = f"{base}_{method.lower()}_{counter}"
                counter += 1
            used[name] = True
            rows.append({
                "name": name,
                "method": method,
                "rule": rule,
                "path": rule.rule,
                "endpoint": rule.endpoint,
            })
    return rows


def _tool_schema(row):
    properties = {}
    required = []
    for arg in sorted(row["rule"].arguments):
        properties[arg] = _converter_schema(row["rule"], arg)
        required.append(arg)

    override_props, override_required = _COMMON_SCHEMAS.get((row["method"], row["path"]), ({}, []))
    properties.update(override_props)
    for item in override_required:
        if item not in required:
            required.append(item)

    properties["_query"] = {
        "type": "object",
        "description": "Optional query string parameters for the HTTP route",
        "additionalProperties": True,
    }
    properties["_headers"] = {
        "type": "object",
        "description": "Optional additional HTTP headers for the internal route call",
        "additionalProperties": {"type": "string"},
    }
    if row["method"] not in {"GET", "HEAD"}:
        properties["_body"] = {
            "type": "object",
            "description": "Optional raw JSON body. When present, it is merged with top-level arguments.",
            "additionalProperties": True,
        }

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def _tools_list(app):
    tools = []
    for row in _route_table(app):
        method = row["method"]
        path = _path_template(row["rule"])
        tools.append({
            "name": row["name"],
            "title": f"CoAgent {path}",
            "description": f"Call Hermes CoAgent endpoint {method} {path}",
            "inputSchema": _tool_schema(row),
            "annotations": {
                "method": method,
                "path": row["path"],
                "endpoint": row["endpoint"],
            },
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
    view_args = {}
    for arg in sorted(rule.arguments):
        if arg not in args:
            raise KeyError(arg)
        value = _convert_path_arg(rule, arg, args[arg])
        view_args[arg] = value
        consumed.add(arg)
        path_value = quote(str(value), safe="")
        path = re.sub(r"<(?:[^:<>]+:)?" + re.escape(arg) + r">", path_value, path)
    return path, consumed, view_args


def _response_payload(resp):
    content_type = resp.headers.get("Content-Type", "")
    mimetype = content_type.split(";", 1)[0].strip().lower()
    if "application/json" in content_type:
        return resp.get_json(silent=True)
    data = resp.get_data()
    if mimetype.startswith("image/"):
        return {
            "_mcp_binary": True,
            "mimeType": mimetype,
            "data": base64.b64encode(data).decode("ascii"),
            "size": len(data),
        }
    text = data.decode("utf-8", errors="replace")
    if len(text) > 20000:
        text = text[:20000] + "\n[truncated]"
    return text


def _prepare_body(args, consumed):
    raw_body = args.get("_body")
    body = dict(raw_body) if isinstance(raw_body, dict) else {}
    body.update({k: v for k, v in args.items() if k not in consumed and not k.startswith("_")})
    return body


def _dispatch_route(app, row, path, view_args, method, query, body, headers):
    kwargs = {
        "method": method,
        "query_string": query or {},
        "headers": headers or {},
    }
    if method not in {"GET", "HEAD"}:
        kwargs["json"] = body
    with app.test_request_context(path, **kwargs):
        # Match URL rule so url_rule and view_args are populated correctly
        request.url_rule = row["rule"]
        request.view_args = view_args
        # Run before_request handlers (auth gate lives here)
        rv = app.preprocess_request()
        if rv is not None:
            return rv  # before_request returned a response (auth failed)
        # Dispatch to view function
        rv = app.view_functions[row["rule"].endpoint](**view_args)
        return app.make_response(rv)


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
        path, consumed, view_args = _fill_path(row["rule"], args)
    except (KeyError, ValueError) as exc:
        missing = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        return {"isError": True, "content": [{"type": "text", "text": f"invalid path argument: {missing}"}]}

    headers = {}
    # NEVER forward inbound Authorization — internal dispatch uses its own auth model
    extra_headers = args.get("_headers")
    if isinstance(extra_headers, dict):
        # Block dangerous headers from MCP callers
        blocked = {"host", "cookie", "authorization", "content-length", "transfer-encoding",
                   "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"}
        for k, v in extra_headers.items():
            if str(k).lower() not in blocked:
                headers[str(k)] = str(v)
    query = args.get("_query") if isinstance(args.get("_query"), dict) else {}
    body = _prepare_body(args, consumed)
    method = row["method"]

    try:
        resp = _dispatch_route(app, row, path, view_args, method, query, body, headers)
    except Exception as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
        }

    payload_body = _response_payload(resp)
    structured = {
        "status_code": resp.status_code,
        "headers": {"content-type": resp.headers.get("Content-Type", "")},
        "body": payload_body,
    }
    if isinstance(payload_body, dict) and payload_body.get("_mcp_binary"):
        content = [{
            "type": "image",
            "data": payload_body["data"],
            "mimeType": payload_body["mimeType"],
        }]
    else:
        content = [{"type": "text", "text": json.dumps(structured, indent=2, default=str)}]
    return {
        "isError": resp.status_code >= 400,
        "content": content,
        "structuredContent": structured,
    }


def _resources_list(app):
    return {
        "resources": [
            {
                "uri": "coagent://tools",
                "name": "tools",
                "title": "CoAgent MCP Tools",
                "description": "Current auto-discovered MCP tool list",
                "mimeType": "application/json",
            },
            {
                "uri": "coagent://routes",
                "name": "routes",
                "title": "CoAgent Flask Routes",
                "description": "Current Flask URL map exposed through MCP",
                "mimeType": "application/json",
            },
            {
                "uri": "coagent://version",
                "name": "version",
                "title": "CoAgent Version",
                "description": "Version, build, and server metadata",
                "mimeType": "application/json",
            },
            {
                "uri": "coagent://health",
                "name": "health",
                "title": "CoAgent Health",
                "description": "Basic local health status",
                "mimeType": "application/json",
            },
        ]
    }


def _read_resource(app, params):
    uri = params.get("uri") if isinstance(params, dict) else None
    if uri == "coagent://tools":
        text = json.dumps({"tools": _tools_list(app)}, indent=2, default=str)
    elif uri == "coagent://routes":
        routes = [
            {
                "name": row["name"],
                "method": row["method"],
                "path": _path_template(row["rule"]),
                "endpoint": row["endpoint"],
            }
            for row in _route_table(app)
        ]
        text = json.dumps({"routes": routes, "count": len(routes)}, indent=2)
    elif uri == "coagent://version":
        text = json.dumps({
            "agent": AGENT_NAME,
            "version": VERSION,
            "build": BUILD,
            "protocolVersion": MCP_PROTOCOL_VERSION,
        }, indent=2)
    elif uri == "coagent://health":
        text = json.dumps({
            "status": "ok",
            "agent": AGENT_NAME,
            "version": VERSION,
            "time": datetime.now(timezone.utc).isoformat(),
        }, indent=2)
    else:
        return None
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}


def _initialize_result(params):
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    protocol_version = requested if requested == MCP_PROTOCOL_VERSION else MCP_PROTOCOL_VERSION
    return {
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"listChanged": True},
        },
        "serverInfo": {
            "name": AGENT_NAME,
            "title": "Hermes CoAgent MCP Bridge",
            "version": VERSION,
        },
        "instructions": "Tools are local Hermes CoAgent desktop automation endpoints. Tool calls are dispatched to the registered Flask route handlers.",
    }


def _handle_rpc(app, message):
    if not isinstance(message, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")
    if message.get("jsonrpc") != "2.0":
        return _jsonrpc_error(message.get("id"), -32600, "jsonrpc must be exactly '2.0'")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    is_notification = request_id is None

    # Validate params type per JSON-RPC 2.0
    if not isinstance(params, (dict, list)):
        return _jsonrpc_error(request_id, -32602, "params must be an Object or Array")

    try:
        if method == "initialize":
            _broadcast("initialized", {"time": time.time(), "client": params})
            return _jsonrpc_result(request_id, _initialize_result(params))
        if method == "notifications/initialized":
            if request_id is not None:
                return _jsonrpc_error(request_id, -32600, "notifications must not have an id")
            _broadcast("initialized", {"time": time.time()})
            return None
        if method == "ping":
            return _jsonrpc_result(request_id, {})
        if method == "tools/list":
            return _jsonrpc_result(request_id, {"tools": _tools_list(app)})
        if method == "tools/call":
            result = _call_tool(app, params)
            _broadcast("tool_call", {
                "time": time.time(),
                "name": params.get("name") if isinstance(params, dict) else None,
                "isError": result.get("isError"),
            })
            return _jsonrpc_result(request_id, result)
        if method == "resources/list":
            return _jsonrpc_result(request_id, _resources_list(app))
        if method == "resources/read":
            result = _read_resource(app, params)
            if result is None:
                return _jsonrpc_error(request_id, -32002, "Resource not found", {"uri": params.get("uri")})
            return _jsonrpc_result(request_id, result)
        return None if is_notification else _jsonrpc_error(request_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        import logging
        logging.getLogger("coagent.mcp").error("MCP tool call failed: %s", exc, exc_info=True)
        return _jsonrpc_error(request_id, -32603, "Internal error")


def _mcp_events_response():
    def generate():
        q = queue.Queue(maxsize=100)
        with _SUBSCRIBERS_LOCK:
            if len(_SUBSCRIBERS) >= _MAX_SSE_SUBSCRIBERS:
                yield f"event: error\\ndata: {json.dumps({'error': 'max subscribers reached'})}\\n\\n"
                return
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


def _jsonrpc_http_response(app, payload):
    if isinstance(payload, list):
        responses = [_handle_rpc(app, item) for item in payload]
        responses = [item for item in responses if item is not None]
        if not responses:
            return Response(status=202)
        return jsonify(responses)
    response = _handle_rpc(app, payload)
    if response is None:
        return Response(status=202)
    return jsonify(response)


def run_stdio_server(app, stdin=None, stdout=None, stderr=None):
    """Run MCP over newline-delimited stdio without starting the HTTP server."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    stderr.write(f"[MCP] {AGENT_NAME} v{VERSION} stdio ready\n")
    stderr.flush()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, list):
                responses = [_handle_rpc(app, item) for item in payload]
                responses = [item for item in responses if item is not None]
                if not responses:
                    continue
                response = responses
            else:
                response = _handle_rpc(app, payload)
                if response is None:
                    continue
        except Exception as exc:
            response = _jsonrpc_error(None, -32700, f"Parse error: {exc}")
        stdout.write(json.dumps(response, separators=(",", ":"), default=str) + "\n")
        stdout.flush()


def register_routes(app, state, require_auth):
    @app.route("/mcp", methods=["GET", "POST"])
    @require_auth
    def route_mcp_jsonrpc():
        if request.method == "GET":
            return _mcp_events_response()
        payload = request.get_json(force=True, silent=True)
        return _jsonrpc_http_response(app, payload)

    @app.route("/mcp/events", methods=["GET"])
    @require_auth
    def route_mcp_events():
        return _mcp_events_response()

    @app.route("/mcp/sse", methods=["GET"])
    @require_auth
    def route_mcp_sse():
        return _mcp_events_response()

    @app.route("/mcp/message", methods=["POST"])
    @require_auth
    def route_mcp_message():
        payload = request.get_json(force=True, silent=True)
        return _jsonrpc_http_response(app, payload)

    @app.route("/mcp/tools", methods=["GET"])
    @require_auth
    def route_mcp_tools():
        tools = _tools_list(app)
        return jsonify({"tools": tools, "count": len(tools)})

    @app.route("/mcp/config", methods=["GET"])
    @require_auth
    def route_mcp_config():
        """Generate MCP client config for Claude Desktop, Cursor, VS Code, Hermes."""
        from shared import _get_host_ip
        lan_ip = getattr(_get_host_ip, '__call__', lambda: "127.0.0.1")()
        if not lan_ip or lan_ip == "127.0.0.1":
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                s.close()
            except Exception:
                lan_ip = "127.0.0.1"
        port = getattr(app.config, "SERVER_NAME", "").split(":")[-1] if getattr(app.config, "SERVER_NAME", "") else "9123"

        return jsonify({
            "server": AGENT_NAME,
            "version": VERSION,
            "protocol_version": MCP_PROTOCOL_VERSION,
            "endpoint": f"http://{lan_ip}:{port}/mcp",
            "configs": {
                "claude_desktop": {
                    "mcpServers": {
                        "coagent": {
                            "url": f"http://{lan_ip}:{port}/mcp",
                            "headers": {
                                "Authorization": "Bearer YOUR_TOKEN_HERE"
                            }
                        }
                    }
                },
                "cursor": {
                    "mcpServers": {
                        "coagent": {
                            "url": f"http://{lan_ip}:{port}/mcp",
                            "headers": {
                                "Authorization": "Bearer YOUR_TOKEN_HERE"
                            }
                        }
                    }
                },
                "hermes": f"""mcp_servers:
  coagent:
    url: \"http://{lan_ip}:{port}/mcp\"
    headers:
      Authorization: \"Bearer YOUR_TOKEN_HERE\"
    timeout: 120
    connect_timeout: 30""",
                "vscode_copilot": {
                    "servers": {
                        "coagent": {
                            "type": "http",
                            "url": f"http://{lan_ip}:{port}/mcp",
                            "headers": {
                                "Authorization": "Bearer YOUR_TOKEN_HERE"
                            }
                        }
                    }
                }
            },
            "note": "Replace YOUR_TOKEN_HERE with your actual bearer token from the .token file."
        })

    state.mcp = {
        "protocol_version": MCP_PROTOCOL_VERSION,
        "transport": ["http", "sse", "stdio"],
        "tools": lambda: _tools_list(app),
    }
