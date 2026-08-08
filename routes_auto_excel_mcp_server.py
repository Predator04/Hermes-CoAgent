# Auto-added feature: haris-musa/excel-mcp-server (3984 stars)
# Description: A Model Context Protocol server for Excel file manipulation
# Source: https://github.com/haris-musa/excel-mcp-server

import os
import shutil
import subprocess
from pathlib import Path

from flask import jsonify
from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "haris-musa/excel-mcp-server",
    "stars": 3984,
    "desc": "A Model Context Protocol server for Excel file manipulation",
    "url": "https://github.com/haris-musa/excel-mcp-server",
    "added": "2026-07-04",
    "command": "excel-mcp or uvx excel-mcp-server",
}


def _find_excel_mcp():
    configured = os.environ.get("EXCEL_MCP_CMD", "").strip()
    if configured and shutil.which(configured):
        return configured
    # Try common install methods
    candidates = [
        "excel-mcp",
        "excel-mcp.exe",
        "excel-mcp-server",
        "excel_mcp_server",
    ]
    for cmd in candidates:
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _clean_file_path(value):
    path = str(value or "").strip()
    if not path:
        raise ValueError("file path must not be empty")
    if "\x00" in path:
        raise ValueError("file path cannot contain null bytes")
    return path


def _optional_int(value, field, default, minimum, maximum):
    if value in (None, ""):
        return default
    number = int(value)
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return number


def register_routes(app, state, require_auth):
    @app.route("/auto/excel_mcp_server/info", methods=["GET"])
    @require_auth
    def route_excel_mcp_server_info():
        return jsonify(FEATURE_INFO)

    @app.route("/auto/excel_mcp_server/ping", methods=["GET"])
    @require_auth
    def route_excel_mcp_server_ping():
        cmd = _find_excel_mcp()
        return jsonify({
            "status": "ok",
            "feature": "haris-musa/excel-mcp-server",
            "available": bool(cmd),
            "command": cmd or "excel-mcp",
            "hint": "Install with `uvx excel-mcp-server` or `pip install excel-mcp-server`",
        })

    @app.route("/auto/excel_mcp_server/execute", methods=["POST"])
    @require_auth
    def route_excel_mcp_server_execute():
        """Execute an Excel operation via the MCP server.
        
        Body: {
            "file": "C:\\path\\to\\workbook.xlsx",
            "operation": "read_cell",
            "params": {"sheet": "Sheet1", "cell": "A1"}
        }
        """
        data = _json_body()
        missing = _missing_field(data, "file")
        if missing:
            return missing
        if "operation" not in data:
            return _missing_field("operation")

        cmd = _find_excel_mcp()
        if not cmd:
            return jsonify({
                "ok": False,
                "error": "excel-mcp command not found on PATH",
                "hint": "Install with `uvx excel-mcp-server` or `pip install excel-mcp-server`",
            }), 503

        try:
            file_path = _clean_file_path(data.get("file"))
            operation = str(data.get("operation", "")).strip()
            if not operation:
                raise ValueError("operation must be a non-empty string")
            params = data.get("params", {})
            timeout = _optional_int(data.get("timeout"), "timeout", 60, 5, 300)
        except (ValueError, TypeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        if not Path(file_path).is_file():
            return jsonify({
                "ok": False,
                "error": f"File not found: {file_path}",
            }), 404

        command = [cmd, "--file", file_path, "--operation", operation]
        if params:
            import json as _json
            command.extend(["--params", _json.dumps(params)])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            _log(f"[excel_mcp] Operation timed out after {timeout}s operation={operation}")
            return jsonify({
                "ok": False,
                "error": f"Excel operation timed out after {timeout}s",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }), 504
        except OSError as exc:
            _log(f"[excel_mcp] launch failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        ok = result.returncode == 0
        _log(f"[excel_mcp] exit={result.returncode} operation={operation}")
        return jsonify({
            "ok": ok,
            "exit_code": result.returncode,
            "file": file_path,
            "operation": operation,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 200 if ok else 502
