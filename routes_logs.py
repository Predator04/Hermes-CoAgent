"""Log analyzer routes."""

import re
import time
from collections import Counter

from flask import Blueprint, jsonify

from routes_bypass import _json_payload
from shared import SERVER_LOG, _wrap_registered_blueprint_routes


logs_bp = Blueprint("logs_analyzer", __name__)

RULES = [
    ("MSS capture failed", "Try installing DXCam for faster screenshots"),
    ("UIA", "UIA engine may need restart"),
    ("timeout", "Consider increasing timeout value"),
    ("No module named", "Missing dependency. Run POST /deps/auto"),
    ("MemoryError", "Memory leak detected. Consider restart"),
]


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def _read_lines(limit=None):
    if not SERVER_LOG.exists():
        return []
    lines = SERVER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:] if limit else lines


def _is_error(line):
    lowered = line.lower()
    return any(token in lowered for token in ("error", "exception", "traceback", "failed", "[500]"))


def _is_warn(line):
    lowered = line.lower()
    return "warn" in lowered or "warning" in lowered


def _normalize_error(line):
    text = re.sub(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?\s*", "", line).strip()
    text = re.sub(r"\b0x[0-9a-fA-F]+\b", "0x...", text)
    text = re.sub(r"\b\d{4,}\b", "N", text)
    return text[:300]


def _suggestion(error):
    for needle, suggestion in RULES:
        haystack = error if needle == "UIA" else error.lower()
        wanted = needle if needle == "UIA" else needle.lower()
        if wanted in haystack:
            return suggestion
    return "Inspect the endpoint logs and retry with diagnostics enabled"


@logs_bp.route("/logs/analyze", methods=["POST"])
def route_logs_analyze():
    data = _json_payload()
    try:
        limit = max(100, min(int(data.get("lines", 1000)), 20000))
    except (TypeError, ValueError):
        limit = 1000
    lines = _read_lines(limit)
    errors = [_normalize_error(line) for line in lines if _is_error(line)]
    counts = Counter(errors)
    common = [{"error": message, "count": count} for message, count in counts.most_common(20)]
    suggestions = [
        {
            "error": item["error"],
            "count": item["count"],
            "suggestion": f"{item['error']} occurred {item['count']} times. Consider: {_suggestion(item['error'])}",
        }
        for item in common[:10]
    ]
    return jsonify({
        "log": str(SERVER_LOG),
        "lines_scanned": len(lines),
        "error_count": len(errors),
        "error_frequency": dict(counts.most_common(50)),
        "most_common_errors": common,
        "suggestions": suggestions,
    })


@logs_bp.route("/logs/summary", methods=["GET"])
def route_logs_summary():
    lines = _read_lines()
    modified_age = None
    if SERVER_LOG.exists():
        modified_age = round(time.time() - SERVER_LOG.stat().st_mtime, 2)
    return jsonify({
        "log": str(SERVER_LOG),
        "total_lines": len(lines),
        "error_count": sum(1 for line in lines if _is_error(line)),
        "warn_count": sum(1 for line in lines if _is_warn(line)),
        "last_modified_age_seconds": modified_age,
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(logs_bp)
    _wrap_registered_blueprint_routes(app, logs_bp.name, require_auth)
