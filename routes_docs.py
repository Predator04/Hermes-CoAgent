"""OpenAPI and Swagger UI routes for Hermes CoAgent."""

from copy import deepcopy

from flask import Blueprint, Response, jsonify

from shared import (
    AGENT_NAME,
    COAGENT_DIR,
    SERVER_PORT,
    VERSION,
    get_host_ip,
    _wrap_registered_blueprint_routes,
)


docs_bp = Blueprint("docs", __name__)


def _json_schema(description="JSON response"):
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"type": "object", "additionalProperties": True}
            }
        },
    }


def _text_schema(description="Plain-text response"):
    return {
        "description": description,
        "content": {"text/plain": {"schema": {"type": "string"}}},
    }


def _param(name, location="path", schema_type="string", required=True, description=""):
    return {
        "name": name,
        "in": location,
        "required": required,
        "schema": {"type": schema_type},
        "description": description or name,
    }


def _body(properties=None, required=None, description="JSON request body"):
    return {
        "required": True,
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                    "additionalProperties": True,
                }
            }
        },
    }


def _op(tag, summary, description, parameters=None, request_body=None, responses=None, security=None):
    operation = {
        "tags": [tag],
        "summary": summary,
        "description": description,
        "responses": responses or {"200": _json_schema()},
    }
    if parameters:
        operation["parameters"] = parameters
    if request_body:
        operation["requestBody"] = request_body
    if security is not None:
        operation["security"] = security
    return operation


COMMON_COORDS = {
    "x": {"type": "number", "description": "Screen X coordinate"},
    "y": {"type": "number", "description": "Screen Y coordinate"},
}


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": AGENT_NAME,
        "version": VERSION,
        "description": (
            f"{AGENT_NAME} desktop automation API. CoAgent directory: {COAGENT_DIR}"
        ),
    },
    "servers": [
        {"url": f"http://127.0.0.1:{SERVER_PORT}", "description": "Localhost"},
        {"url": f"http://{get_host_ip()}:{SERVER_PORT}", "description": "Detected host IP"},
    ],
    "security": [{"BearerAuth": []}],
    "components": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Hermes CoAgent bearer token",
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {"error": {"type": "string"}},
                "additionalProperties": True,
            },
            "GenericObject": {"type": "object", "additionalProperties": True},
            "AgentExecRequest": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "agent": {"type": "string", "enum": ["codex", "claude", "gemini", "opencode"]},
                    "model": {"type": "string"},
                    "timeout": {"type": "integer"},
                    "workdir": {"type": "string"},
                },
                "required": ["prompt"],
            },
        },
    },
    "tags": [
        {"name": "Core"},
        {"name": "Mouse"},
        {"name": "Keyboard"},
        {"name": "Screen"},
        {"name": "UIA"},
        {"name": "Windows"},
        {"name": "Files"},
        {"name": "Agent Gateway"},
        {"name": "Telegram"},
        {"name": "Config"},
        {"name": "Metrics"},
        {"name": "System"},
        {"name": "Clipboard"},
        {"name": "Macro"},
        {"name": "Webhooks"},
        {"name": "Updates"},
        {"name": "Plugins"},
    ],
    "paths": {
        "/ping": {
            "get": _op(
                "Core",
                "Ping server",
                "Return a lightweight liveness response and uptime.",
                security=[],
            )
        },
        "/version": {
            "get": _op(
                "Core",
                "Get version",
                "Return the agent name, build, feature list, and module list.",
                security=[],
            )
        },
        "/health": {
            "get": _op(
                "Core",
                "Get health",
                "Return process health and version metadata.",
                security=[],
            )
        },
        "/mouse/move": {
            "post": _op(
                "Mouse",
                "Move cursor",
                "Move the mouse pointer to absolute screen coordinates.",
                request_body=_body(COMMON_COORDS, ["x", "y"]),
            )
        },
        "/mouse/click": {
            "post": _op(
                "Mouse",
                "Click",
                "Click at the provided coordinates or current pointer location.",
                request_body=_body({**COMMON_COORDS, "button": {"type": "string"}}, []),
            )
        },
        "/mouse/dblclick": {
            "post": _op(
                "Mouse",
                "Double-click",
                "Double-click at the provided coordinates or current pointer location.",
                request_body=_body(COMMON_COORDS, []),
            )
        },
        "/mouse/rclick": {
            "post": _op(
                "Mouse",
                "Right-click",
                "Right-click at the provided coordinates or current pointer location.",
                request_body=_body(COMMON_COORDS, []),
            )
        },
        "/mouse/drag": {
            "post": _op(
                "Mouse",
                "Drag cursor",
                "Drag from a start coordinate to an end coordinate.",
                request_body=_body(
                    {
                        "x1": {"type": "number"},
                        "y1": {"type": "number"},
                        "x2": {"type": "number"},
                        "y2": {"type": "number"},
                        "duration": {"type": "number"},
                    },
                    ["x1", "y1", "x2", "y2"],
                ),
            )
        },
        "/mouse/scroll": {
            "post": _op(
                "Mouse",
                "Scroll",
                "Scroll the active target by a wheel delta.",
                request_body=_body({"delta": {"type": "integer"}}, ["delta"]),
            )
        },
        "/cursor/pos": {
            "get": _op("Mouse", "Get cursor position", "Return current cursor coordinates.")
        },
        "/key/type": {
            "post": _op(
                "Keyboard",
                "Type text",
                "Type text through the active input channel.",
                request_body=_body({"text": {"type": "string"}}, ["text"]),
            )
        },
        "/key/press": {
            "post": _op(
                "Keyboard",
                "Press key",
                "Press a single key or key combination.",
                request_body=_body({"key": {"type": "string"}}, ["key"]),
            )
        },
        "/screen/jpeg": {
            "get": _op(
                "Screen",
                "Capture JPEG",
                "Return the current screen as a JPEG response.",
                responses={"200": {"description": "JPEG image", "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}},
            )
        },
        "/screen/base64": {
            "get": _op("Screen", "Capture base64", "Return a base64-encoded screenshot.")
        },
        "/screen/describe": {
            "get": _op("Screen", "Describe screen", "Return OCR and visual screen description data.")
        },
        "/som/screenshot": {
            "get": _op("Screen", "Capture SOM screenshot", "Return screenshot with set-of-marks overlays.")
        },
        "/uia/tree": {
            "get": _op("UIA", "Get UIA tree", "Return the active accessibility tree.")
        },
        "/uia/find/{name}": {
            "get": _op(
                "UIA",
                "Find element by name",
                "Find a UI Automation element by name.",
                parameters=[_param("name", description="Element name")],
            )
        },
        "/uia/click/{name}": {
            "post": _op(
                "UIA",
                "Click element by name",
                "Click a UI Automation element by name.",
                parameters=[_param("name", description="Element name")],
            )
        },
        "/windows": {
            "get": _op("Windows", "List windows", "Return visible windows and metadata.")
        },
        "/windows/activate": {
            "post": _op(
                "Windows",
                "Activate window",
                "Bring a matching window to the foreground.",
                request_body=_body({"title": {"type": "string"}, "pid": {"type": "integer"}}, []),
            )
        },
        "/windows/close": {
            "post": _op(
                "Windows",
                "Close window",
                "Close a matching window.",
                request_body=_body({"title": {"type": "string"}, "pid": {"type": "integer"}}, []),
            )
        },
        "/windows/{pid}": {
            "get": _op(
                "Windows",
                "Get process windows",
                "Return windows associated with a process id.",
                parameters=[_param("pid", schema_type="integer", description="Process id")],
            )
        },
        "/file/list": {
            "post": _op(
                "Files",
                "List files",
                "List files under a permitted path.",
                request_body=_body({"path": {"type": "string"}}, ["path"]),
            )
        },
        "/file/read": {
            "post": _op(
                "Files",
                "Read file",
                "Read a permitted local file.",
                request_body=_body({"path": {"type": "string"}}, ["path"]),
            )
        },
        "/file/write": {
            "post": _op(
                "Files",
                "Write file",
                "Write content to a permitted local file.",
                request_body=_body({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            )
        },
        "/file/delete": {
            "post": _op(
                "Files",
                "Delete file",
                "Delete a permitted file or confirmed directory.",
                request_body=_body({"path": {"type": "string"}, "confirm": {"type": "boolean"}}, ["path"]),
            )
        },
        "/file/upload": {
            "post": _op(
                "Files",
                "Upload file",
                "Upload file content to a permitted local path.",
                request_body=_body({"path": {"type": "string"}, "content_base64": {"type": "string"}}, ["path", "content_base64"]),
            )
        },
        "/agent/exec": {
            "post": _op(
                "Agent Gateway",
                "Execute agent",
                "Run an installed AI agent CLI with a prompt.",
                request_body={"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentExecRequest"}}}},
            )
        },
        "/agent/audit": {
            "post": _op(
                "Agent Gateway",
                "Audit files",
                "Run a security or quality audit over selected paths.",
                request_body=_body(
                    {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "focus": {"type": "string", "enum": ["security", "quality", "all"]},
                        "agent": {"type": "string"},
                    },
                    ["paths"],
                ),
            )
        },
        "/agent/plan": {
            "post": _op(
                "Agent Gateway",
                "Plan implementation",
                "Generate a read-only implementation plan.",
                request_body=_body({"task": {"type": "string"}, "context": {"type": "string"}}, ["task"]),
            )
        },
        "/agent/status": {
            "get": _op(
                "Agent Gateway",
                "Agent status",
                "List detected local agent CLIs and availability.",
            ),
            "post": _op(
                "Agent Gateway",
                "Agent status",
                "Compatibility entry for clients that POST status probes.",
            ),
        },
        "/agent/exec/stream/{log_id}": {
            "get": _op(
                "Agent Gateway",
                "Stream agent execution",
                "Stream Server-Sent Events for an agent execution log.",
                parameters=[_param("log_id", description="Execution log id")],
                responses={"200": _text_schema("SSE stream")},
            )
        },
        "/telegram/configure": {
            "post": _op(
                "Telegram",
                "Configure Telegram",
                "Save Telegram bot token and target chat id.",
                request_body=_body({"bot_token": {"type": "string"}, "chat_id": {"type": "string"}}, ["bot_token", "chat_id"]),
            )
        },
        "/telegram/send": {
            "post": _op(
                "Telegram",
                "Send Telegram message",
                "Send a message through the configured Telegram relay.",
                request_body=_body({"text": {"type": "string"}}, ["text"]),
            )
        },
        "/telegram/config": {
            "get": _op("Telegram", "Get Telegram config", "Return masked Telegram relay configuration.")
        },
        "/config": {
            "get": _op("Config", "Get config", "Return CoAgent configuration.")
        },
        "/config/update": {
            "post": _op(
                "Config",
                "Update config",
                "Update CoAgent configuration values.",
                request_body=_body({"values": {"type": "object", "additionalProperties": True}}, ["values"]),
            )
        },
        "/metrics": {
            "get": _op(
                "Metrics",
                "Prometheus metrics",
                "Return Prometheus text-format counters, histograms, and gauges.",
                responses={"200": _text_schema("Prometheus text metrics")},
                security=[],
            )
        },
        "/process/start": {
            "post": _op(
                "System",
                "Start process",
                "Start a local process.",
                request_body=_body({"cmd": {"type": "string"}, "cwd": {"type": "string"}}, ["cmd"]),
            )
        },
        "/process/list": {
            "get": _op("System", "List processes", "Return running process metadata.")
        },
        "/power/shutdown": {
            "post": _op("System", "Shutdown host", "Request host shutdown.")
        },
        "/power/restart": {
            "post": _op("System", "Restart host", "Request host restart.")
        },
        "/clipboard/get": {
            "post": _op("Clipboard", "Get clipboard", "Return current clipboard text.")
        },
        "/clipboard/set": {
            "post": _op(
                "Clipboard",
                "Set clipboard",
                "Set clipboard text.",
                request_body=_body({"text": {"type": "string"}}, ["text"]),
            )
        },
        "/macro/list": {
            "post": _op("Macro", "List macros", "Return saved macro names.")
        },
        "/macro/save": {
            "post": _op(
                "Macro",
                "Save macro",
                "Persist a macro definition.",
                request_body=_body({"name": {"type": "string"}, "actions": {"type": "array", "items": {"type": "object"}}}, ["name", "actions"]),
            )
        },
        "/macro/run": {
            "post": _op(
                "Macro",
                "Run macro",
                "Run a saved macro.",
                request_body=_body({"name": {"type": "string"}}, ["name"]),
            )
        },
        "/webhooks/register": {
            "post": _op(
                "Webhooks",
                "Register webhook",
                "Register a webhook URL and event list.",
                request_body=_body(
                    {
                        "url": {"type": "string", "format": "uri"},
                        "events": {"type": "array", "items": {"type": "string"}},
                    },
                    ["url", "events"],
                ),
            )
        },
        "/webhooks/list": {
            "get": _op("Webhooks", "List webhooks", "List registered webhooks without secrets.")
        },
        "/webhooks/{id}": {
            "delete": _op(
                "Webhooks",
                "Delete webhook",
                "Delete a registered webhook.",
                parameters=[_param("id", description="Webhook id")],
            )
        },
        "/update/check": {
            "get": _op("Updates", "Check for update", "Check GitHub for the latest release.")
        },
        "/update/apply": {
            "post": _op("Updates", "Apply update", "Download and apply the latest release tarball.")
        },
        "/plugins/list": {
            "get": _op("Plugins", "List plugins", "List discovered plugins.")
        },
        "/plugins/install": {
            "post": _op(
                "Plugins",
                "Install plugin",
                "Install a plugin package.",
                request_body=_body({"name": {"type": "string"}, "source": {"type": "string"}}, ["name"]),
            )
        },
        "/plugins/uninstall": {
            "post": _op(
                "Plugins",
                "Uninstall plugin",
                "Uninstall a plugin package.",
                request_body=_body({"name": {"type": "string"}}, ["name"]),
            )
        },
    },
}


def _spec():
    return deepcopy(OPENAPI_SPEC)


@docs_bp.route("/docs.json", methods=["GET"])
def route_docs_json():
    return jsonify(_spec())


@docs_bp.route("/docs", methods=["GET"])
def route_docs():
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes CoAgent API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
  <style>
    html, body { margin: 0; padding: 0; background: #f7f7f7; }
    #swagger-ui { min-height: 100vh; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.addEventListener("load", function () {
      SwaggerUIBundle({
        url: "/docs.json",
        dom_id: "#swagger-ui",
        presets: [SwaggerUIBundle.presets.apis],
        layout: "BaseLayout",
        deepLinking: true
      });
    });
  </script>
</body>
</html>
"""
    response = Response(html, mimetype="text/html")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


def register_routes(app, state, require_auth):
    app.register_blueprint(docs_bp)
    # /docs.json exposes the full endpoint inventory, the machine LAN IP and
    # the COAGENT_DIR path — keep it behind the same bearer auth as the API.
    _wrap_registered_blueprint_routes(app, docs_bp.name, require_auth)
