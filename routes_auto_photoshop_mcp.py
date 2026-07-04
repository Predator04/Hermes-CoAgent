# Auto-added feature: alisaitteke/photoshop-mcp (155 stars)
# Description: MCP server for Adobe Photoshop automation — 50+ tools for design, image editing, workflow
# Source: https://github.com/alisaitteke/photoshop-mcp

import os
import shutil
import subprocess
from pathlib import Path

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "alisaitteke/photoshop-mcp",
    "stars": 155,
    "desc": "MCP server for Adobe Photoshop automation — 50+ tools for design, image editing, workflow",
    "url": "https://github.com/alisaitteke/photoshop-mcp",
    "added": "2026-07-04",
    "command": "npx @photoshops/mcp-server",
}


def _find_photoshop_mcp():
    """Check if Photoshop MCP server is available via npx or local install."""
    configured = os.environ.get("PHOTOSHOP_MCP_CMD", "").strip()
    if configured and (shutil.which(configured) or Path(configured).is_file()):
        return configured
    # Check if npx is available and the package is installed
    npx = shutil.which("npx")
    if npx:
        return f"{npx} @photoshops/mcp-server"
    return None


def _clean_string(value, field):
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field} must be a non-empty string")
    if "\x00" in s:
        raise ValueError(f"{field} cannot contain null bytes")
    return s


def _clean_script(value):
    script = str(value or "").strip()
    if not script:
        raise ValueError("script must be a non-empty string")
    if "\x00" in script:
        raise ValueError("script cannot contain null bytes")
    if len(script) > 50000:
        raise ValueError("script exceeds maximum length (50000 chars)")
    return script


def register_routes(app, state, require_auth):
    @app.route("/auto/photoshop_mcp/info", methods=["GET"])
    @require_auth
    def route_photoshop_mcp_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/photoshop_mcp/ping", methods=["GET"])
    @require_auth
    def route_photoshop_mcp_ping():
        cmd = _find_photoshop_mcp()
        return jsonify({
            "status": "ok",
            "feature": "alisaitteke/photoshop-mcp",
            "available": bool(cmd),
            "command": cmd or "npx @photoshops/mcp-server",
            "hint": "Install with `npm install -g @photoshops/mcp-server` or `npx @photoshops/mcp-server`",
        })

    @app.route("/auto/photoshop_mcp/execute", methods=["POST"])
    @require_auth
    def route_photoshop_mcp_execute():
        """Execute a Photoshop action via the MCP server.
        
        Body: {
            "action": "createDocument",
            "params": {"width": 1920, "height": 1080, "resolution": 72, "fill": "white"}
        }
        """
        data = _json_body()
        if "action" not in data:
            return _missing_field("action")

        cmd = _find_photoshop_mcp()
        if not cmd:
            return jsonify({
                "ok": False,
                "error": "Photoshop MCP server not found",
                "hint": "Install with `npm install -g @photoshops/mcp-server`",
            }), 503

        try:
            action = _clean_string(data.get("action"), "action")
            params = data.get("params", {})
            timeout = max(1, min(int(data.get("timeout", 120)), 600))
        except (ValueError, TypeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        import json as _json
        try:
            result = subprocess.run(
                cmd.split(),
                input=_json.dumps({
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": action,
                        "arguments": params,
                    },
                    "id": 1,
                }),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[photoshop_mcp] Action timed out after {timeout}s action={action}")
            return jsonify({
                "ok": False,
                "error": f"Photoshop action timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[photoshop_mcp] Launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[photoshop_mcp] exit={result.returncode} action={action}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "action": action,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502

    @app.route("/auto/photoshop_mcp/run_script", methods=["POST"])
    @require_auth
    def route_photoshop_mcp_run_script():
        """Run a raw ExtendScript in Photoshop via the MCP server.
        
        Body: {
            "script": "app.activeDocument.resizeImage(800, 600, 72, ResampleMethod.BICUBIC);"
        }
        """
        data = _json_body()
        if "script" not in data:
            return _missing_field("script")

        cmd = _find_photoshop_mcp()
        if not cmd:
            return jsonify({
                "ok": False,
                "error": "Photoshop MCP server not found",
                "hint": "Install with `npm install -g @photoshops/mcp-server`",
            }), 503

        try:
            script = _clean_script(data.get("script"))
            timeout = max(1, min(int(data.get("timeout", 120)), 600))
        except (ValueError, TypeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        import json as _json
        try:
            result = subprocess.run(
                cmd.split(),
                input=_json.dumps({
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "runScript",
                        "arguments": {"script": script},
                    },
                    "id": 1,
                }),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[photoshop_mcp] runScript timed out after {timeout}s")
            return jsonify({
                "ok": False,
                "error": f"Photoshop script timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[photoshop_mcp] Launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[photoshop_mcp] runScript exit={result.returncode}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
