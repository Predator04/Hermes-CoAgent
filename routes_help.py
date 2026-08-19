"""System help & documentation routes."""

import json

from flask import Blueprint, jsonify, request

from shared import VERSION

help_bp = Blueprint("help", __name__)


@help_bp.route("/help", methods=["GET"])
def route_help():
    """Return comprehensive help/documentation for all features."""
    fmt = request.args.get("format", "json")

    help_data = {
        "agent": "Hermes CoAgent",
        "version": VERSION,
        "description": "Desktop automation agent — control Windows via REST API",
        "auth": {
            "method": "Bearer token",
            "header": "Authorization: Bearer ***",
            "exempt_paths": ["/", "/health", "/ping", "/help", "/version", "/static/"],
        },
        "features": {
            "Core Desktop Control": {
                "mouse_click": {"method": "POST", "path": "/mouse/click", "body": {"x": 100, "y": 200, "button": "left"}, "desc": "Click at screen coordinates"},
                "mouse_move": {"method": "POST", "path": "/mouse/move", "body": {"x": 100, "y": 200}, "desc": "Move mouse to coordinates"},
                "mouse_drag": {"method": "POST", "path": "/mouse/drag", "body": {"x": 100, "y": 200, "x2": 300, "y2": 400}, "desc": "Drag from (x,y) to (x2,y2)"},
                "mouse_scroll": {"method": "POST", "path": "/mouse/scroll", "body": {"clicks": -3}, "desc": "Scroll mouse wheel"},
                "key_type": {"method": "POST", "path": "/key/type", "body": {"text": "hello world"}, "desc": "Type text"},
                "key_press": {"method": "POST", "path": "/key/press", "body": {"keys": ["ctrl", "c"]}, "desc": "Press key combination"},
                "screen": {"method": "GET", "path": "/screen", "desc": "Take screenshot (JPEG)"},
                "fresh_screenshot": {"method": "GET", "path": "/screen/fresh", "desc": "Fresh full screenshot"},
            },
            "UIA Automation": {
                "uia_tree": {"method": "GET", "path": "/uia/tree", "desc": "Get UIA accessibility tree (flat list)"},
                "uia_window_tree": {"method": "GET", "path": "/uia/tree/window/<name>", "desc": "UIA tree for a specific window"},
                "uia_click": {"method": "POST", "path": "/uia/click/<index>", "desc": "Click UIA element by index"},
                "uia_click_by_name": {"method": "POST", "path": "/uia/click_by_name", "body": {"name": "OK", "control_type": "Button"}, "desc": "Click UIA element by name/automation_id"},
                "uia_type": {"method": "POST", "path": "/uia/type/<index>", "body": {"text": "hello"}, "desc": "Type into UIA element"},
                "uia_find": {"method": "POST", "path": "/uia/find", "body": {"name": "Notepad", "control_type": "Window"}, "desc": "Find UIA element"},
            },
            "SOM (Scene Object Model)": {
                "som": {"method": "GET", "path": "/som/screenshot", "desc": "Get SOM (interactive screenshot with element boxes)"},
                "som_bridge": {"method": "GET", "path": "/som/bridge", "desc": "Bridge UIA element to clickable SOM"},
                "som_per_window": {"method": "GET", "path": "/som/per-window", "desc": "Per-window SOM snapshots"},
                "som_point": {"method": "POST", "path": "/som/point", "body": {"x": 100, "y": 200}, "desc": "Get UIA element at screen coordinates"},
            },
            "OCR": {
                "ocr_screen": {"method": "POST", "path": "/uia/ocr", "desc": "OCR entire screen (text)"},
                "ocr_find": {"method": "POST", "path": "/ocr/find", "body": {"text": "Search..."}, "desc": "Find text on screen"},
                "ocr_click": {"method": "POST", "path": "/ocr/click", "body": {"text": "OK", "occurrence": 0}, "desc": "Find text and click it"},
            },
            "Process & Window Management": {
                "process_list": {"method": "GET", "path": "/process/list", "desc": "List running processes"},
                "process_start": {"method": "POST", "path": "/process/start", "body": {"path": "notepad.exe", "args": ""}, "desc": "Start a process"},
                "process_kill": {"method": "POST", "path": "/process/kill", "body": {"name": "notepad.exe"}, "desc": "Kill a process by name"},
                "window_list": {"method": "GET", "path": "/window/list", "desc": "List all visible windows"},
                "window_activate": {"method": "POST", "path": "/window/activate", "body": {"title": "Notepad"}, "desc": "Activate/focus a window"},
                "window_close": {"method": "POST", "path": "/window/close", "body": {"title": "Untitled - Notepad"}, "desc": "Close a window"},
            },
            "AI Copilot": {
                "copilot_goal": {"method": "POST", "path": "/copilot/goal", "body": {"goal": "open notepad and type hello", "max_steps": 10}, "desc": "Execute multi-step automation goal via AI"},
                "copilot_status": {"method": "GET", "path": "/copilot/goal/<goal_id>", "desc": "Check copilot goal execution status"},
                "copilot_stop": {"method": "POST", "path": "/copilot/stop/<goal_id>", "desc": "Stop a running copilot goal"},
            },
            "Scheduled Recipes": {
                "recipes_create": {"method": "POST", "path": "/recipes/create", "body": {"name": "daily-backup", "steps": [{"action": "click", "params": {"target": "button"}}], "schedule": "every 5 minutes"}, "desc": "Create automation recipe with schedule"},
                "recipes_list": {"method": "GET", "path": "/recipes/list", "desc": "List all recipes"},
                "recipes_get": {"method": "GET", "path": "/recipes/<recipe_id>", "desc": "Get recipe details"},
                "recipes_run": {"method": "POST", "path": "/recipes/<recipe_id>/run", "desc": "Run a recipe immediately"},
                "recipes_toggle": {"method": "POST", "path": "/recipes/<recipe_id>/toggle", "desc": "Enable/disable a recipe"},
                "recipes_delete": {"method": "POST", "path": "/recipes/<recipe_id>/delete", "desc": "Delete a recipe"},
            },
            "Browser Automation (Playwright)": {
                "browser_open": {"method": "POST", "path": "/browser/open", "body": {"url": "https://example.com", "headless": False}, "desc": "Open browser window"},
                "browser_status": {"method": "GET", "path": "/browser/status", "desc": "Get browser status"},
                "browser_list": {"method": "GET", "path": "/browser/list", "desc": "List all open browsers"},
                "browser_navigate": {"method": "POST", "path": "/browser/navigate/<id>", "body": {"url": "https://google.com"}, "desc": "Navigate to URL"},
                "browser_click": {"method": "POST", "path": "/browser/click/<id>", "body": {"selector": "h1"}, "desc": "Click a CSS selector"},
                "browser_type": {"method": "POST", "path": "/browser/type/<id>", "body": {"selector": "#search", "text": "hello"}, "desc": "Type text into element"},
                "browser_extract": {"method": "POST", "path": "/browser/extract/<id>", "body": {"selector": "h1"}, "desc": "Extract text from page"},
                "browser_screenshot": {"method": "GET", "path": "/browser/screenshot/<id>", "desc": "Take browser screenshot (returns PNG)"},
                "browser_evaluate": {"method": "POST", "path": "/browser/evaluate/<id>", "body": {"script": "document.title"}, "desc": "Execute JavaScript in browser"},
                "browser_close": {"method": "POST", "path": "/browser/close/<id>", "desc": "Close browser window"},
            },
            "Self-Healing": {
                "healer_status": {"method": "GET", "path": "/healer/status", "desc": "Get healer status (memory, health, route probing)"},
                "healer_config": {"method": "GET", "path": "/healer/config", "desc": "Current healer configuration"},
                "healer_check": {"method": "POST", "path": "/healer/check", "desc": "Run a healer check on demand"},
            },
            "Mobile Remote": {
                "mobile_dashboard": {"method": "GET", "path": "/mobile", "desc": "Mobile-friendly remote desktop dashboard (HTML)"},
                "mobile_view": {"method": "GET", "path": "/mobile/view", "desc": "Mobile viewport stream endpoint"},
            },
            "Dashboard": {
                "dashboard": {"method": "GET", "path": "/dashboard", "desc": "Full web dashboard with live controls"},
            },
            "WebSocket & Streaming": {
                "stream": {"method": "GET", "path": "/screen/stream", "desc": "WebSocket/HTTP screen stream (JPEG frames)"},
                "stream_mjpeg": {"method": "GET", "path": "/screen/stream/mjpeg", "desc": "MJPEG multipart screen stream"},
            },
            "System": {
                "ping": {"method": "GET", "path": "/ping", "desc": "Health ping"},
                "version": {"method": "GET", "path": "/version", "desc": "Version and feature list"},
                "help": {"method": "GET", "path": "/help?format=json|text", "desc": "This help page"},
                "metrics": {"method": "GET", "path": "/metrics", "desc": "Prometheus metrics"},
                "logs": {"method": "GET", "path": "/logs", "desc": "Recent console logs"},
            },
        }
    }

    if fmt == "text":
        lines = [f"HERMES COAGENT {VERSION} — HELP", "=" * 50, ""]
        lines.append("AUTH: All endpoints require header: Authorization: Bearer ***")
        lines.append("")
        for category, endpoints in help_data["features"].items():
            lines.append(f"[{category}]")
            for name, info in endpoints.items():
                parts = [f"  {info['method']:6s} {info['path']}"]
                if "body" in info:
                    parts.append(f"          Body: {json.dumps(info['body'])}")
                parts.append(f"          {info['desc']}")
                lines.append("\n".join(parts))
            lines.append("")
        return "\n".join(lines)

    return jsonify(help_data)


def register_routes(app, state, require_auth):
    app.register_blueprint(help_bp)
    state.help = {"version": VERSION}
