"""Brainstem/Neocortex LLM Routing.

Fast local model (Ollama) handles simple tasks (brainstem).
Heavy cloud model (GPT-4o/Claude) handles complex reasoning (neocortex).
Routes based on task complexity and content length.
"""
import logging
import threading
import time

from flask import Blueprint, jsonify, request
from shared import _wrap_registered_blueprint_routes

_LOGGER = logging.getLogger(__name__)
brainstem_bp = Blueprint("brainstem", __name__)

_ROUTER_STATE = {
    "brainstem_model": "ollama:qwen3.6:27b",
    "neocortex_model": "openai:gpt-4o",
    "complexity_threshold": 0.5,
    "brainstem_calls": 0,
    "neocortex_calls": 0,
    "avg_brainstem_latency": 0.0,
    "avg_neocortex_latency": 0.0,
    "tokens_saved_est": 0,
}
_ROUTER_LOCK = threading.Lock()

_SIMPLE_VERBS = {"open", "close", "click", "type", "press", "scroll", "find",
                 "launch", "run", "save", "copy", "paste", "minimize", "maximize"}


def _debug_failure(context, exc):
    _LOGGER.debug("brainstem %s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _estimate_complexity(task):
    """Return a complexity score 0.0-1.0 based on task characteristics."""
    task = task.strip()
    if not task:
        return 0.0
    # Length factor
    length_score = min(1.0, len(task) / 500)
    # Verb factor
    words = task.lower().split()
    simple_verb_count = sum(1 for w in words if w in _SIMPLE_VERBS)
    total_verbs = max(1, sum(1 for w in words if any(c.isalpha() for c in w) and len(w) > 2))
    verb_ratio = simple_verb_count / total_verbs if total_verbs else 0
    # Multi-step indicator (presence of "then", "and", commas, numbers)
    multi_step = any(word in task.lower() for word in ["then", "after", "first", "second", "finally"])
    multi_step_score = 0.3 if multi_step else 0
    # Combined score
    score = (length_score * 0.3) + ((1 - verb_ratio) * 0.4) + multi_step_score
    return min(1.0, score)


def _call_llm(provider_key, prompt, model, timeout=60):
    """Call an LLM via the routes_agent provider system."""
    try:
        from routes_agent import _call_provider, _provider_settings
        provider_name = provider_key.split(":")[0]
        settings = _provider_settings(provider_name, {"model": model})
        result = _call_provider(provider_name, prompt, settings, timeout)
        return result.get("content", "")
    except Exception as exc:
        _debug_failure(f"call_llm {provider_key}", exc)
        return f"[Error: {exc}]"


@brainstem_bp.route("/brainstem/route", methods=["POST"])
def _brainstem_route():
    body = request.get_json(force=True, silent=True) or {}
    task = body.get("task", "")
    if not task:
        return jsonify({"ok": False, "error": "missing task"}), 400

    force_neocortex = body.get("force_neocortex", False)
    complexity = _estimate_complexity(task)

    start = time.time()
    if force_neocortex or complexity >= _ROUTER_STATE["complexity_threshold"]:
        # Neocortex
        model = _ROUTER_STATE["neocortex_model"]
        provider = model.split(":")[0]
        response = _call_llm(provider, task, model.split(":", 1)[1] if ":" in model else None)
        latency = time.time() - start
        with _ROUTER_LOCK:
            _ROUTER_STATE["neocortex_calls"] += 1
            n = _ROUTER_STATE["neocortex_calls"]
            _ROUTER_STATE["avg_neocortex_latency"] = (
                (_ROUTER_STATE["avg_neocortex_latency"] * (n - 1) + latency) / n
            )
        return jsonify({
            "ok": True,
            "router": "neocortex",
            "complexity": round(complexity, 3),
            "task": task,
            "response": response,
            "latency_secs": round(latency, 2),
        })
    else:
        # Brainstem
        model = _ROUTER_STATE["brainstem_model"]
        provider = model.split(":")[0]
        response = _call_llm(provider, task, model.split(":", 1)[1] if ":" in model else None)
        latency = time.time() - start
        with _ROUTER_LOCK:
            _ROUTER_STATE["brainstem_calls"] += 1
            _ROUTER_STATE["tokens_saved_est"] += int(len(response) * 0.5)
            n = _ROUTER_STATE["brainstem_calls"]
            _ROUTER_STATE["avg_brainstem_latency"] = (
                (_ROUTER_STATE["avg_brainstem_latency"] * (n - 1) + latency) / n
            )
        return jsonify({
            "ok": True,
            "router": "brainstem",
            "complexity": round(complexity, 3),
            "task": task,
            "response": response,
            "latency_secs": round(latency, 2),
        })


@brainstem_bp.route("/brainstem/query", methods=["POST"])
def _brainstem_query():
    body = request.get_json(force=True, silent=True) or {}
    prompt = body.get("prompt", "")
    force_neocortex = body.get("force_neocortex", False)
    if not prompt:
        return jsonify({"ok": False, "error": "missing prompt"}), 400
    # Map prompt→task and inline routing instead of calling _brainstem_route()
    # which re-reads `task` from the (already-consumed) request body.
    complexity = _estimate_complexity(prompt)
    start = time.time()
    if force_neocortex or complexity >= _ROUTER_STATE["complexity_threshold"]:
        model = _ROUTER_STATE["neocortex_model"]
        provider = model.split(":")[0]
        response = _call_llm(provider, prompt, model.split(":")[1] if ":" in model else None)
        latency = time.time() - start
        with _ROUTER_LOCK:
            _ROUTER_STATE["neocortex_calls"] += 1
            n = _ROUTER_STATE["neocortex_calls"]
            _ROUTER_STATE["avg_neocortex_latency"] = (
                (_ROUTER_STATE["avg_neocortex_latency"] * (n - 1) + latency) / n
            )
        return jsonify({
            "ok": True,
            "router": "neocortex",
            "complexity": round(complexity, 3),
            "task": prompt,
            "response": response,
            "latency_secs": round(latency, 2),
        })
    else:
        model = _ROUTER_STATE["brainstem_model"]
        provider = model.split(":")[0]
        response = _call_llm(provider, prompt, model.split(":")[1] if ":" in model else None)
        latency = time.time() - start
        with _ROUTER_LOCK:
            _ROUTER_STATE["brainstem_calls"] += 1
            _ROUTER_STATE["tokens_saved_est"] += int(len(response) * 0.5)
            n = _ROUTER_STATE["brainstem_calls"]
            _ROUTER_STATE["avg_brainstem_latency"] = (
                (_ROUTER_STATE["avg_brainstem_latency"] * (n - 1) + latency) / n
            )
        return jsonify({
            "ok": True,
            "router": "brainstem",
            "complexity": round(complexity, 3),
            "task": prompt,
            "response": response,
            "latency_secs": round(latency, 2),
        })


@brainstem_bp.route("/brainstem/status", methods=["GET"])
def _brainstem_status():
    with _ROUTER_LOCK:
        return jsonify({
            "ok": True,
            "config": {
                "brainstem_model": _ROUTER_STATE["brainstem_model"],
                "neocortex_model": _ROUTER_STATE["neocortex_model"],
                "complexity_threshold": _ROUTER_STATE["complexity_threshold"],
            },
            "stats": {
                "brainstem_calls": _ROUTER_STATE["brainstem_calls"],
                "neocortex_calls": _ROUTER_STATE["neocortex_calls"],
                "avg_brainstem_latency_secs": round(_ROUTER_STATE["avg_brainstem_latency"], 3),
                "avg_neocortex_latency_secs": round(_ROUTER_STATE["avg_neocortex_latency"], 3),
                "tokens_saved_est": _ROUTER_STATE["tokens_saved_est"],
            },
        })


@brainstem_bp.route("/brainstem/configure", methods=["POST"])
def _brainstem_configure():
    body = request.get_json(force=True, silent=True) or {}
    with _ROUTER_LOCK:
        for key in ("brainstem_model", "neocortex_model", "complexity_threshold"):
            if key in body:
                _ROUTER_STATE[key] = body[key]
    return jsonify({"ok": True, "config": {
        "brainstem_model": _ROUTER_STATE["brainstem_model"],
        "neocortex_model": _ROUTER_STATE["neocortex_model"],
        "complexity_threshold": _ROUTER_STATE["complexity_threshold"],
    }})


def register_routes(app, state, require_auth):
    app.register_blueprint(brainstem_bp)
    _wrap_registered_blueprint_routes(app, brainstem_bp.name, require_auth)
    _LOGGER.info("Brainstem/Neocortex routing routes registered")
