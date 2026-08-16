# Auto-added feature: ollama/ollama (178596 stars)
# Local LLM runtime — pull, serve, and run open-weight models via CLI + REST API
# Source: https://github.com/ollama/ollama
# Install: winget install Ollama.Ollama

import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

from flask import jsonify, request

from shared import _json_body, _log, _missing_field

FEATURE_INFO = {
    "repo": "ollama/ollama",
    "stars": 178596,
    "desc": "Ollama runs open-weight LLMs (Kimi-K2.6, GLM-5.2, DeepSeek, Qwen, Llama, gpt-oss) locally with a one-line install. It exposes a clean REST API on 127.0.0.1:11434 and a CLI for pulling, serving, generating, and embedding. This route lets CoAgent list models, pull new ones, run non-streaming generation/chat, and produce embeddings — a local reasoning backend the agent can call without any cloud dependency.",
    "url": "https://github.com/ollama/ollama",
    "added": "2026-08-15",
    "command": "ollama run <model> \"<prompt>\"",
    "install": {
        "winget": "winget install Ollama.Ollama",
        "scoop": "scoop install ollama",
    },
    "endpoints": {
        "/auto/ollama/info": "Feature metadata, install status, server reachability",
        "/auto/ollama/ping": "Health check",
        "/auto/ollama/list": "GET — local models (from /api/tags)",
        "/auto/ollama/ps": "GET — currently loaded models (from /api/ps)",
        "/auto/ollama/show": "GET — model metadata (param size, quantization, template)",
        "/auto/ollama/pull": "POST — pull a model by name",
        "/auto/ollama/generate": "POST — non-streaming text generation",
        "/auto/ollama/chat": "POST — chat completion (messages array)",
        "/auto/ollama/embeddings": "POST — embedding vector for a prompt",
    },
}

_DEFAULT_BASE = "http://127.0.0.1:11434"
_PULL_LOCK = threading.Lock()


def _find_ollama():
    """Locate the ollama CLI on this system."""
    exe = shutil.which("ollama")
    if exe:
        return exe
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _server_base():
    """Return the base URL of a reachable ollama server, or None."""
    base = os.environ.get("OLLAMA_HOST", "").strip()
    if not base:
        base = _DEFAULT_BASE
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base.rstrip("/")


def _http(method, path, payload=None, timeout=120):
    """Small urllib helper returning (status, parsed_json_or_none, raw_text)."""
    url = _server_base() + path
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


def _cli_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        out = (r.stdout.strip() or r.stderr.strip())
        return out.split("\n")[0].strip()
    except Exception:
        return "unknown"


def _installed_info():
    """Common bits for info/ping: exe presence + server reachability."""
    exe = _find_ollama()
    server_ok = False
    server_version = None
    status, j, _ = _http("GET", "/api/version", timeout=5)
    if status == 200 and isinstance(j, dict):
        server_ok = True
        server_version = j.get("version")
    return exe, server_ok, server_version


def register_routes(app, state, require_auth):
    @app.route("/auto/ollama/info", methods=["GET"])
    @require_auth
    def route_auto_ollama_info():
        exe, server_ok, server_version = _installed_info()
        info = dict(FEATURE_INFO)
        info["installed"] = exe is not None
        if exe:
            info["path"] = exe
            info["version"] = _cli_version(exe)
        info["server"] = {
            "reachable": server_ok,
            "version": server_version,
            "base_url": _server_base(),
        }
        return jsonify(info)

    @app.route("/auto/ollama/ping", methods=["GET"])
    @require_auth
    def route_auto_ollama_ping():
        exe, server_ok, _ = _installed_info()
        return jsonify({
            "status": "ok" if (exe or server_ok) else "not_installed",
            "feature": "ollama/ollama",
            "installed": exe is not None,
            "server_reachable": server_ok,
            "path": exe,
        })

    @app.route("/auto/ollama/list", methods=["GET"])
    @require_auth
    def route_auto_ollama_list():
        status, j, _ = _http("GET", "/api/tags", timeout=10)
        if status == 200 and isinstance(j, dict):
            models = j.get("models") or []
            return jsonify({
                "count": len(models),
                "models": [
                    {
                        "name": m.get("name"),
                        "model": m.get("model"),
                        "size": m.get("size"),
                        "modified_at": m.get("modified_at"),
                        "quantization_level": m.get("details", {}).get("quantization_level") if isinstance(m.get("details"), dict) else None,
                    }
                    for m in models
                ],
            })
        return jsonify({
            "error": "ollama server unreachable",
            "hint": "Install with: winget install Ollama.Ollama, then run 'ollama serve'",
            "detail": j if j is not None else "connection failed",
        }), 503

    @app.route("/auto/ollama/ps", methods=["GET"])
    @require_auth
    def route_auto_ollama_ps():
        status, j, _ = _http("GET", "/api/ps", timeout=10)
        if status == 200 and isinstance(j, dict):
            models = j.get("models") or []
            return jsonify({"running": len(models), "models": models})
        return jsonify({"error": "ollama server unreachable", "running": 0}), 503

    @app.route("/auto/ollama/show", methods=["GET"])
    @require_auth
    def route_auto_ollama_show():
        name = request.args.get("model") or request.args.get("name")
        if not name:
            return jsonify({"error": "missing query param 'model'"}), 400
        status, j, _ = _http("POST", "/api/show", {"name": name}, timeout=15)
        if status == 200 and isinstance(j, dict):
            return jsonify({
                "model": name,
                "details": j.get("details"),
                "parameters": j.get("parameters"),
                "template": j.get("template"),
                "system": j.get("system"),
                "license": j.get("license"),
                "modelfile": j.get("modelfile"),
            })
        return jsonify({"error": f"could not show model {name!r}", "detail": j}), 404

    @app.route("/auto/ollama/pull", methods=["POST"])
    @require_auth
    def route_auto_ollama_pull():
        body = _json_body()
        name = body.get("model") or body.get("name")
        if not name:
            return jsonify({"error": _missing_field("model")}), 400
        name = str(name).strip()
        if not name or any(c in name for c in ("\n", "\r", " ")):
            return jsonify({"error": "invalid model name"}), 400
        _insecure = body.get("insecure", False)
        insecure = _insecure is True or str(_insecure).strip().lower() in ("true", "1", "yes", "on")

        if not _PULL_LOCK.acquire(blocking=False):
            return jsonify({"error": "a pull is already in progress", "success": False}), 409

        try:
            _log(f"ollama_pull: {name}")
            payload = {"name": name, "stream": False}
            if insecure:
                payload["insecure"] = True
            status, j, raw = _http("POST", "/api/pull", payload, timeout=1800)
            ok = status == 200 and (isinstance(j, dict) and j.get("status") == "success")
            return jsonify({
                "success": ok,
                "model": name,
                "http_status": status,
                "result": j if j is not None else raw,
            }), (200 if ok else 502)
        except Exception as e:
            _log(f"ollama_pull: Error: {e}")
            return jsonify({"error": str(e), "success": False}), 500
        finally:
            _PULL_LOCK.release()

    @app.route("/auto/ollama/generate", methods=["POST"])
    @require_auth
    def route_auto_ollama_generate():
        body = _json_body()
        model = body.get("model")
        prompt = body.get("prompt")
        if not model:
            return jsonify({"error": _missing_field("model")}), 400
        if prompt is None:
            return jsonify({"error": _missing_field("prompt")}), 400

        payload = {"model": str(model), "prompt": str(prompt), "stream": False}
        if body.get("options") and isinstance(body["options"], dict):
            payload["options"] = body["options"]
        if body.get("system"):
            payload["system"] = str(body["system"])
        if body.get("template"):
            payload["template"] = str(body["template"])
        if body.get("raw") is not None:
            payload["raw"] = bool(body["raw"])
        if body.get("keep_alive") is not None:
            payload["keep_alive"] = body["keep_alive"]

        status, j, _ = _http("POST", "/api/generate", payload, timeout=600)
        if status == 200 and isinstance(j, dict):
            return jsonify({
                "model": model,
                "response": j.get("response"),
                "done": j.get("done"),
                "context_length": j.get("prompt_eval_count"),
                "generated_tokens": j.get("eval_count"),
                "total_duration_ns": j.get("total_duration"),
            })
        return jsonify({"error": f"generate failed (status {status})", "detail": j}), 502

    @app.route("/auto/ollama/chat", methods=["POST"])
    @require_auth
    def route_auto_ollama_chat():
        body = _json_body()
        model = body.get("model")
        messages = body.get("messages")
        if not model:
            return jsonify({"error": _missing_field("model")}), 400
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": _missing_field("messages")}), 400

        payload = {"model": str(model), "messages": messages, "stream": False}
        if body.get("options") and isinstance(body["options"], dict):
            payload["options"] = body["options"]
        if body.get("keep_alive") is not None:
            payload["keep_alive"] = body["keep_alive"]

        status, j, _ = _http("POST", "/api/chat", payload, timeout=600)
        if status == 200 and isinstance(j, dict):
            msg = j.get("message") or {}
            return jsonify({
                "model": model,
                "message": msg,
                "done": j.get("done"),
                "prompt_eval_count": j.get("prompt_eval_count"),
                "eval_count": j.get("eval_count"),
            })
        return jsonify({"error": f"chat failed (status {status})", "detail": j}), 502

    @app.route("/auto/ollama/embeddings", methods=["POST"])
    @require_auth
    def route_auto_ollama_embeddings():
        body = _json_body()
        model = body.get("model")
        prompt = body.get("prompt")
        if not model:
            return jsonify({"error": _missing_field("model")}), 400
        if prompt is None:
            return jsonify({"error": _missing_field("prompt")}), 400

        payload = {"model": str(model), "prompt": str(prompt)}
        if body.get("options") and isinstance(body["options"], dict):
            payload["options"] = body["options"]

        status, j, _ = _http("POST", "/api/embeddings", payload, timeout=300)
        if status == 200 and isinstance(j, dict):
            emb = j.get("embedding")
            return jsonify({
                "model": model,
                "dimensions": len(emb) if isinstance(emb, list) else None,
                "embedding": emb,
            })
        return jsonify({"error": f"embeddings failed (status {status})", "detail": j}), 502
