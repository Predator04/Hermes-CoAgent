# Auto-added feature: CursorTouch/Windows-MCP (6342 stars)
# Description: MCP Server for Computer Use in Windows — screenshot, click, type,
#   PowerShell, file system, and app control via MCP protocol
# Source: https://github.com/CursorTouch/Windows-MCP

import json
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request

from flask import jsonify, request
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "CursorTouch/Windows-MCP",
    "stars": 6342,
    "desc": "MCP Server for Computer Use in Windows — screenshot, click, type, PowerShell, "
            "file system, file system, and app control integration via SSE transport",
    "url": "https://github.com/CursorTouch/Windows-MCP",
    "added": "2026-07-06",
    "command": "windows-mcp serve | uvx windows-mcp serve",
}

# Default port for the Windows-MCP SSE server
_DEFAULT_PORT = 8124
_SERVER_PROCESS = None


def _find_windows_mcp():
    return shutil.which("windows-mcp") or shutil.which("windows-mcp.exe")


def _is_windows_mcp_installed():
    """Check if Windows-MCP is available (pip-installed package or uvx)."""
    # First try pip-installed windows-mcp
    exe = _find_windows_mcp()
    if exe:
        try:
            result = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Try uvx as fallback
    uvx = shutil.which("uvx")
    if uvx:
        try:
            result = subprocess.run(
                [uvx, "windows-mcp", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass

    return False


def _get_mcp_server_url(port):
    return f"http://127.0.0.1:{port}/mcp"


def _mcp_request(port, method, params=None):
    """Send a JSON-RPC request to the Windows-MCP SSE server."""
    url = _get_mcp_server_url(port)
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000) % 1000000,
        "method": method,
        "params": params or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:500]
        return {"error": {"message": f"HTTP {exc.code}: {body_text}"}}
    except urllib.error.URLError as exc:
        return {"error": {"message": f"Connection failed: {exc.reason}"}}
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": {"message": str(exc)}}


def _ping_mcp_server(port=_DEFAULT_PORT):
    """Try to ping the MCP server by sending a lightweight request."""
    result = _mcp_request(port, "ping")
    return result.get("result") == "pong" or "result" in result


def register_routes(app, state, require_auth):
    @app.route("/auto/windows_mcp/info", methods=["GET"])
    @require_auth
    def route_auto_windows_mcp_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/windows_mcp/ping", methods=["GET"])
    @require_auth
    def route_auto_windows_mcp_ping():
        installed = _is_windows_mcp_installed()
        server_running = False
        port = _DEFAULT_PORT
        if installed:
            server_running = _ping_mcp_server(port)

        return jsonify({
            "status": "ok",
            "feature": "CursorTouch/Windows-MCP",
            "installed": installed,
            "server_running": server_running,
            "port": port,
            "server_url": _get_mcp_server_url(port) if installed else None,
            "command": "windows-mcp serve",
        })

    @app.route("/auto/windows_mcp/server/start", methods=["POST"])
    @require_auth
    def route_auto_windows_mcp_server_start():
        global _SERVER_PROCESS

        if _SERVER_PROCESS and _SERVER_PROCESS.poll() is None:
            return jsonify({
                "ok": True,
                "message": "Server is already running",
                "pid": _SERVER_PROCESS.pid,
            })

        if not _is_windows_mcp_installed():
            return jsonify({
                "ok": False,
                "error": "Windows-MCP not installed",
                "hint": "Install via: pip install windows-mcp",
            }), 503

        data = _json_body()
        port = _DEFAULT_PORT
        if data:
            try:
                port = max(1024, min(int(data.get("port", _DEFAULT_PORT)), 65535))
            except (TypeError, ValueError):
                port = _DEFAULT_PORT

        exe = _find_windows_mcp()
        if exe:
            cmd = [exe, "serve", "--transport", "sse", "--host", "127.0.0.1",
                   "--port", str(port)]
        else:
            # Fall back to uvx
            uvx = shutil.which("uvx")
            if not uvx:
                return jsonify({
                    "ok": False,
                    "error": "Neither windows-mcp nor uvx found on PATH",
                }), 503
            cmd = [uvx, "windows-mcp", "serve", "--transport", "sse",
                   "--host", "127.0.0.1", "--port", str(port)]

        try:
            _SERVER_PROCESS = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except OSError as exc:
            _log(f"[windows_mcp] server start failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        # Give it a moment to start
        time.sleep(1.5)

        running = _SERVER_PROCESS.poll() is None
        _log(f"[windows_mcp] server start pid={_SERVER_PROCESS.pid} running={running}")
        return jsonify({
            "ok": running,
            "pid": _SERVER_PROCESS.pid if running else None,
            "port": port,
            "server_url": _get_mcp_server_url(port),
            "message": "Server started" if running else "Server failed to start",
        })

    @app.route("/auto/windows_mcp/server/stop", methods=["POST"])
    @require_auth
    def route_auto_windows_mcp_server_stop():
        global _SERVER_PROCESS

        if not _SERVER_PROCESS or _SERVER_PROCESS.poll() is not None:
            return jsonify({
                "ok": True,
                "message": "No running server to stop",
            })

        try:
            if hasattr(signal, "CTRL_C_EVENT"):
                _SERVER_PROCESS.send_signal(signal.CTRL_C_EVENT)
            else:
                _SERVER_PROCESS.terminate()
            _SERVER_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _SERVER_PROCESS.kill()
            _SERVER_PROCESS.wait(timeout=3)
        except OSError as exc:
            _log(f"[windows_mcp] server stop failed: {exc}")

        _log(f"[windows_mcp] server stopped (was pid={_SERVER_PROCESS.pid})")
        _SERVER_PROCESS = None
        return jsonify({"ok": True, "message": "Server stopped"})

    @app.route("/auto/windows_mcp/tool", methods=["POST"])
    @require_auth
    def route_auto_windows_mcp_tool():
        data = _json_body()
        missing = _missing_field(data, "tool")
        if missing:
            return missing

        tool = str(data.get("tool", "")).strip()
        if not tool:
            return jsonify({"ok": False, "error": "tool must not be empty"}), 400

        params = data.get("params", {})
        if not isinstance(params, dict):
            return jsonify({"ok": False, "error": "params must be a dict"}), 400

        port = _DEFAULT_PORT
        try:
            port = max(1024, min(int(data.get("port", _DEFAULT_PORT)), 65535))
        except (TypeError, ValueError):
            port = _DEFAULT_PORT

        if not _ping_mcp_server(port):
            return jsonify({
                "ok": False,
                "error": "Windows-MCP server is not running on port " + str(port),
                "hint": "Start it via /auto/windows_mcp/server/start first",
            }), 503

        result = _mcp_request(port, "tools/call", {
            "name": tool,
            "arguments": params,
        })

        if "error" in result:
            _log(f"[windows_mcp] tool={tool} error={result['error']}")
            return jsonify({
                "ok": False,
                "error": result["error"].get("message", str(result["error"])),
            }), 502

        _log(f"[windows_mcp] tool={tool} ok")
        return jsonify({
            "ok": True,
            "tool": tool,
            "result": result.get("result"),
        })

    @app.route("/auto/windows_mcp/tools", methods=["GET"])
    @require_auth
    def route_auto_windows_mcp_tools():
        """List available tools from the Windows-MCP server."""
        port = _DEFAULT_PORT
        try:
            port = max(1024, min(int(request.args.get("port", _DEFAULT_PORT, type=int)), 65535))
        except (TypeError, ValueError):
            port = _DEFAULT_PORT

        if not _ping_mcp_server(port):
            return jsonify({
                "ok": False,
                "error": f"Windows-MCP server not running on port {port}",
            }), 503

        result = _mcp_request(port, "tools/list")
        if "error" in result:
            return jsonify({
                "ok": False,
                "error": result["error"].get("message", str(result["error"])),
            }), 502

        tools = result.get("result", {}).get("tools", [])
        return jsonify({
            "ok": True,
            "count": len(tools),
            "tools": [{"name": t.get("name"), "description": t.get("description", "")[:120]}
                      for t in tools],
        })

    @app.route("/auto/windows_mcp/screenshot", methods=["GET"])
    @require_auth
    def route_auto_windows_mcp_screenshot():
        """Take a screenshot using Windows-MCP's Screenshot tool."""
        port = _DEFAULT_PORT
        try:
            port = max(1024, min(int(request.args.get("port", _DEFAULT_PORT, type=int)), 65535))
        except (TypeError, ValueError):
            port = _DEFAULT_PORT

        display = request.args.get("display", "0")
        try:
            display = int(display)
        except (TypeError, ValueError):
            display = 0

        if not _ping_mcp_server(port):
            return jsonify({
                "ok": False,
                "error": f"Windows-MCP server not running on port {port}",
                "hint": "Start it via /auto/windows_mcp/server/start first",
            }), 503

        result = _mcp_request(port, "tools/call", {
            "name": "Screenshot",
            "arguments": {"display": [display]},
        })

        if "error" in result:
            _log(f"[windows_mcp] screenshot error={result['error']}")
            return jsonify({
                "ok": False,
                "error": result["error"].get("message", str(result["error"])),
            }), 502

        _log("[windows_mcp] screenshot taken")
        return jsonify({
            "ok": True,
            "result": result.get("result"),
        })
