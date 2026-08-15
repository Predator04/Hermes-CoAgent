# Auto-added feature: ggml-org/llama.cpp (124019 stars)
# Local LLM inference engine — control a running llama-server via its OpenAI-compatible API
# Source: https://github.com/ggml-org/llama.cpp
# Install: GitHub releases (prebuilt Windows binaries: llama-server.exe, llama-cli.exe)

import glob
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ggml-org/llama.cpp",
    "stars": 124019,
    "desc": "llama.cpp is the C/C++ inference engine behind most local LLM serving. Its llama-server binary exposes an OpenAI-compatible REST API (/health, /v1/models, /v1/completions, /v1/chat/completions, /v1/embeddings) that can run quantized GGUF models on CPU or GPU. This route lets CoAgent discover a running llama-server, list its loaded models, generate text, chat, and produce embeddings — a direct bridge to whatever model is already being served locally.",
    "url": "https://github.com/ggml-org/llama.cpp",
    "added": "2026-08-15",
    "command": "llama-server -m model.gguf --port 8080",
    "install": {
        "manual": "Download prebuilt Windows binaries from github.com/ggml-org/llama.cpp/releases",
        "build": "cmake -B build && cmake --build build --config Release",
    },
    "endpoints": {
        "/auto/llama_cpp/info": "Feature metadata, binary detection, server reachability",
        "/auto/llama_cpp/ping": "Health check",
        "/auto/llama_cpp/health": "GET — llama-server /health status",
        "/auto/llama_cpp/models": "GET — loaded models (/v1/models)",
        "/auto/llama_cpp/generate": "POST — text completion (/v1/completions)",
        "/auto/llama_cpp/chat": "POST — chat completion (/v1/chat/completions)",
        "/auto/llama_cpp/embeddings": "POST — embedding vector (/v1/embeddings)",
    },
}

_DEFAULT_PORTS = [8080, 8081, 8082]
_SERVER_URL_ENV = "LLAMA_CPP_SERVER_URL"


def _find_binaries():
    """Locate llama-server / llama-cli binaries on this system."""
    found = {}
    for name in ("llama-server", "llama-cli", "llama-embedding", "llama-quantize"):
        exe = shutil.which(name)
        if exe:
            found[name] = exe
            continue
        # Prebuilt release zips are often unpacked into a versioned folder
        pat = os.path.expandvars(rf"%USERPROFILE%\llama.cpp-*\build\bin\Release\{name}.exe")
        matches = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
        if matches:
            found[name] = matches[0]
    return found


def _server_base(body=None):
    """Resolve the llama-server base URL.

    Priority: explicit request base_url > env var > first reachable default port.
    """
    if isinstance(body, dict):
        explicit = (body.get("base_url") or body.get("server") or "").strip()
        if explicit:
            if not explicit.startswith("http"):
                explicit = "http://" + explicit
            return explicit.rstrip("/")
    env = os.environ.get(_SERVER_URL_ENV, "").strip()
    if env:
        if not env.startswith("http"):
            env = "http://" + env
        return env.rstrip("/")
    for port in _DEFAULT_PORTS:
        base = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return base
        except Exception:
            continue
    return "http://127.0.0.1:8080"  # fallback default


def _http(base, method, path, payload=None, timeout=120):
    url = base + path
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return e.code, None, raw
    except urllib.error.URLError as e:
        return 0, None, str(e.reason)


def _server_status(base):
    status, j, _ = _http(base, "GET", "/health", timeout=5)
    return status == 200, j


def _binary_version(path):
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def register_routes(app, state, require_auth):
    @app.route("/auto/llama_cpp/info", methods=["GET"])
    @require_auth
    def route_auto_llama_cpp_info():
        bins = _find_binaries()
        base = _server_base()
        ok, health = _server_status(base)
        info = dict(FEATURE_INFO)
        info["binaries"] = bins
        info["server"] = {
            "reachable": ok,
            "base_url": base,
            "health": health,
        }
        return jsonify(info)

    @app.route("/auto/llama_cpp/ping", methods=["GET"])
    @require_auth
    def route_auto_llama_cpp_ping():
        bins = _find_binaries()
        base = _server_base()
        ok, _ = _server_status(base)
        status = "ok" if ok else ("installed" if bins else "not_installed")
        return jsonify({
            "status": status,
            "feature": "ggml-org/llama.cpp",
            "binaries": bins,
            "server_reachable": ok,
            "base_url": base,
        })

    @app.route("/auto/llama_cpp/health", methods=["GET"])
    @require_auth
    def route_auto_llama_cpp_health():
        base = _server_base(request.args.to_dict() or None)
        ok, j = _server_status(base)
        return jsonify({
            "reachable": ok,
            "base_url": base,
            "health": j if isinstance(j, dict) else {"status": j},
        }), (200 if ok else 503)

    @app.route("/auto/llama_cpp/models", methods=["GET"])
    @require_auth
    def route_auto_llama_cpp_models():
        base = _server_base(request.args.to_dict() or None)
        status, j, _ = _http(base, "GET", "/v1/models", timeout=10)
        if status == 200 and isinstance(j, dict):
            data = j.get("data") or []
            return jsonify({"count": len(data), "models": data, "base_url": base})
        return jsonify({"error": "could not list models", "base_url": base, "detail": j}), 503

    @app.route("/auto/llama_cpp/generate", methods=["POST"])
    @require_auth
    def route_auto_llama_cpp_generate():
        body = _json_body()
        prompt = body.get("prompt")
        if prompt is None:
            return jsonify({"error": _missing_field("prompt")}), 400

        base = _server_base(body)
        payload = {
            "prompt": str(prompt),
            "max_tokens": int(body.get("max_tokens", 256)),
            "temperature": float(body.get("temperature", 0.8)),
            "stream": False,
        }
        for opt in ("top_p", "top_k", "repeat_penalty", "stop", "seed"):
            if body.get(opt) is not None:
                payload[opt] = body[opt]

        status, j, _ = _http(base, "POST", "/v1/completions", payload, timeout=600)
        if status == 200 and isinstance(j, dict):
            choices = j.get("choices") or []
            text = ""
            if choices:
                text = (choices[0].get("text") or "") or ""
            return jsonify({
                "base_url": base,
                "text": text,
                "usage": j.get("usage"),
                "model": j.get("model"),
            })
        return jsonify({"error": f"completion failed (status {status})", "detail": j}), 502

    @app.route("/auto/llama_cpp/chat", methods=["POST"])
    @require_auth
    def route_auto_llama_cpp_chat():
        body = _json_body()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": _missing_field("messages")}), 400

        base = _server_base(body)
        payload = {
            "messages": messages,
            "max_tokens": int(body.get("max_tokens", 256)),
            "temperature": float(body.get("temperature", 0.8)),
            "stream": False,
        }
        for opt in ("top_p", "top_k", "repeat_penalty", "stop", "seed"):
            if body.get(opt) is not None:
                payload[opt] = body[opt]

        status, j, _ = _http(base, "POST", "/v1/chat/completions", payload, timeout=600)
        if status == 200 and isinstance(j, dict):
            choices = j.get("choices") or []
            msg = {}
            if choices:
                msg = choices[0].get("message") or {}
            return jsonify({
                "base_url": base,
                "message": msg,
                "usage": j.get("usage"),
                "model": j.get("model"),
            })
        return jsonify({"error": f"chat failed (status {status})", "detail": j}), 502

    @app.route("/auto/llama_cpp/embeddings", methods=["POST"])
    @require_auth
    def route_auto_llama_cpp_embeddings():
        body = _json_body()
        text = body.get("input") or body.get("prompt")
        if text is None:
            return jsonify({"error": _missing_field("input")}), 400

        base = _server_base(body)
        payload = {"input": text}
        if body.get("model"):
            payload["model"] = str(body["model"])

        status, j, _ = _http(base, "POST", "/v1/embeddings", payload, timeout=300)
        if status == 200 and isinstance(j, dict):
            data = (j.get("data") or [{}])
            emb = data[0].get("embedding") if data else None
            return jsonify({
                "base_url": base,
                "dimensions": len(emb) if isinstance(emb, list) else None,
                "embedding": emb,
                "model": j.get("model"),
            })
        return jsonify({"error": f"embeddings failed (status {status})", "detail": j}), 502
