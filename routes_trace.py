"""OpenTelemetry / Langfuse-compatible action tracing for CoAgent.

Emits a lightweight in-process span for every wrapped action (mouse, key, UIA,
browser, process, agent-exec, goal-runner step). Persists per-run JSONL to
``COAGENT_DIR/traces/`` so the local trace viewer survives restart. Supports
W3C ``traceparent`` header propagation so an orchestrating agent can link its
own trace to CoAgent's.

Zero required dependencies. If the ``opentelemetry`` package is importable
AND the ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable is set, spans
are also mirrored to that OTLP collector (Langfuse / Arize Phoenix /
Jaeger). Otherwise OTLP is silently skipped.
"""

import functools
import json
import os
import secrets
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _wrap_registered_blueprint_routes


trace_bp = Blueprint("trace", __name__)

TRACES_DIR = COAGENT_DIR / "traces"
try:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

MAX_RUNS_LISTED = 500
MAX_PARAM_CHARS = 2000
MAX_RESULT_CHARS = 2000

_TRACER_LOCK = threading.RLock()
_ACTIVE_RUNS = OrderedDict()   # run_id -> {"path": Path, "started_at": float}
_CURRENT_SPAN = threading.local()

_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
_OTEL_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "hermes-coagent").strip() or "hermes-coagent"
_otel_tracer = None
_otel_init_attempted = False


def _try_init_otlp():
    """Best-effort OTLP init. Returns tracer or None. Never raises."""
    global _otel_tracer, _otel_init_attempted
    if _otel_tracer is not None:
        return _otel_tracer
    if _otel_init_attempted:
        return None
    _otel_init_attempted = True
    if not _OTLP_ENDPOINT:
        return None
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except Exception:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
    except Exception:
        return None
    try:
        provider = TracerProvider(resource=Resource.create({"service.name": _OTEL_SERVICE_NAME}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_OTLP_ENDPOINT)))
        otel_trace.set_tracer_provider(provider)
        _otel_tracer = otel_trace.get_tracer("hermes.coagent")
        _console(f"[trace] OTLP exporter enabled -> {_OTLP_ENDPOINT}")
        return _otel_tracer
    except Exception as exc:
        _console(f"[trace] OTLP init failed: {type(exc).__name__}: {exc}")
        return None


def _rand_hex(n):
    return secrets.token_hex(n // 2)


def _new_trace_id():
    return _rand_hex(32)


def _new_span_id():
    return _rand_hex(16)


_TRACEPARENT_RE = re.compile(
    r"\s*([0-9a-fA-F]{2})-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-([0-9a-fA-F]{2})\s*"
)


def parse_traceparent(value):
    """Parse a W3C ``traceparent`` header. Returns (trace_id, parent_span_id) or (None, None)."""
    if not value:
        return None, None
    match = _TRACEPARENT_RE.fullmatch(str(value))
    if not match:
        return None, None
    return match.group(2).lower(), match.group(3).lower()


def build_traceparent(trace_id, span_id, sampled=True):
    return f"00-{trace_id}-{span_id}-{'01' if sampled else '00'}"


def _summarize(value, limit):
    try:
        if isinstance(value, (dict, list)):
            text = json.dumps(value, default=str, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = repr(value)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "cookie", "credential", "private_key", "session",
)


def _scrub(value, depth=0):
    """Recursively redact sensitive fields before persisting/exporting spans."""
    if depth > 8 or value is None:
        return value
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS):
                out[key] = "[REDACTED]"
            else:
                out[key] = _scrub(val, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value]
    return value


def _cur_stack():
    stack = getattr(_CURRENT_SPAN, "stack", None)
    if stack is None:
        stack = []
        _CURRENT_SPAN.stack = stack
    return stack


def _safe_run_id(run_id):
    """Trace-file names are user-facing paths — restrict to a safe charset."""
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(run_id or ""))[:96]


def _persist_span(run_id, span_dict):
    """Append the span to that run's JSONL file. Best-effort."""
    safe = _safe_run_id(run_id) or _new_trace_id()
    path = TRACES_DIR / f"{safe}.jsonl"
    with _TRACER_LOCK:
        entry = _ACTIVE_RUNS.get(safe)
        if entry is None:
            entry = {"path": path, "started_at": span_dict.get("start", time.time())}
            _ACTIVE_RUNS[safe] = entry
            if len(_ACTIVE_RUNS) > MAX_RUNS_LISTED:
                _ACTIVE_RUNS.popitem(last=False)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(span_dict, default=str, ensure_ascii=False) + "\n")
    except OSError as exc:
        _console(f"[trace] persist failed for {safe}: {type(exc).__name__}: {exc}")


def _export_otlp(span_dict):
    tracer = _try_init_otlp()
    if tracer is None:
        return
    try:
        from opentelemetry import trace as otel_trace
        start_ns = int(span_dict.get("start", time.time()) * 1e9)
        end_ns = int(span_dict.get("end", time.time()) * 1e9)
        with tracer.start_as_current_span(
            span_dict.get("name") or "coagent.action",
            start_time=start_ns,
        ) as s:
            attrs = span_dict.get("attributes") or {}
            for key, value in attrs.items():
                try:
                    s.set_attribute(key, value)
                except Exception:
                    pass
            if span_dict.get("params") is not None:
                try:
                    s.set_attribute("coagent.params", str(span_dict["params"]))
                except Exception:
                    pass
            if span_dict.get("result") is not None:
                try:
                    s.set_attribute("coagent.result", str(span_dict["result"]))
                except Exception:
                    pass
            if span_dict.get("run_id"):
                s.set_attribute("coagent.run_id", str(span_dict["run_id"]))
            if span_dict.get("error"):
                try:
                    s.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR, str(span_dict["error"])))
                except Exception:
                    pass
            s.end(end_time=end_ns)
    except Exception as exc:
        _console(f"[trace] otlp export failed: {type(exc).__name__}: {exc}")


class Span(dict):
    """Dict-based span. Subclass of dict so it JSON-serializes naturally."""

    def __init__(self, name, run_id, parent=None, attributes=None):
        super().__init__()
        self["span_id"] = _new_span_id()
        self["parent_span_id"] = parent
        self["run_id"] = run_id
        self["name"] = name
        self["start"] = time.time()
        self["end"] = None
        self["duration_ms"] = None
        self["status"] = "running"
        self["error"] = None
        self["attributes"] = dict(attributes or {})
        self["params"] = None
        self["result"] = None
        self["before_screenshot"] = None
        self["after_screenshot"] = None

    def set_params(self, value):
        self["params"] = _summarize(value, MAX_PARAM_CHARS)

    def set_result(self, value):
        self["result"] = _summarize(value, MAX_RESULT_CHARS)

    def set_error(self, exc):
        if isinstance(exc, BaseException):
            self["error"] = f"{type(exc).__name__}: {exc}"
        else:
            self["error"] = str(exc)
        self["status"] = "error"

    def set_attribute(self, key, value):
        self["attributes"][str(key)] = value

    def set_screenshots(self, before=None, after=None):
        if before:
            self["before_screenshot"] = before
        if after:
            self["after_screenshot"] = after

    def traceparent(self):
        return build_traceparent(self["run_id"], self["span_id"])

    def end(self):
        if self["end"] is None:
            self["end"] = time.time()
            self["duration_ms"] = int(round((self["end"] - self["start"]) * 1000))
            if self["status"] == "running":
                self["status"] = "ok"
        _persist_span(self["run_id"], dict(self))
        _export_otlp(self)


class _SpanCtx:
    def __init__(self, span_obj):
        self._span = span_obj

    def __enter__(self):
        _cur_stack().append(self._span)
        return self._span

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc is not None:
                self._span.set_error(exc)
        finally:
            self._span.end()
            stack = _cur_stack()
            if stack and stack[-1] is self._span:
                stack.pop()
        return False


def start_span(name, run_id=None, parent=None, attributes=None):
    """Create a span. Inherits run_id/parent from the current thread if unset."""
    if run_id is None and parent is None:
        cur = _cur_stack()
        if cur:
            run_id = cur[-1]["run_id"]
            parent = cur[-1]["span_id"]
    if run_id is None:
        run_id = _new_trace_id()
    return Span(name, run_id=run_id, parent=parent, attributes=attributes)


def span(name, run_id=None, parent=None, attributes=None):
    """Context-manager form: ``with span("x"): ...``."""
    return _SpanCtx(start_span(name, run_id=run_id, parent=parent, attributes=attributes))


def current_span():
    stack = _cur_stack()
    return stack[-1] if stack else None


def _extract_status_and_body(result):
    """Coerce a Flask view return value into (body, status)."""
    if isinstance(result, tuple):
        body = result[0] if result else None
        status = result[1] if len(result) > 1 else 200
    else:
        body = result
        status = getattr(result, "status_code", 200)
    if not isinstance(status, int):
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = 200
    return body, status


def _summarize_response_body(body):
    try:
        from flask import Response
        if hasattr(body, "get_json"):
            return body.get_json(silent=True) or {}
        if isinstance(body, (dict, list)):
            return body
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        if isinstance(body, str):
            try:
                return json.loads(body)
            except Exception:
                return body[:MAX_RESULT_CHARS]
        if isinstance(body, Response):
            try:
                return body.get_json(silent=True) or body.get_data(as_text=True)[:MAX_RESULT_CHARS]
            except Exception:
                return None
    except Exception:
        return None
    return None


def trace_action(name):
    """Decorator: wrap a Flask view so each call emits a span.

    Reads ``traceparent`` from the request headers to link the span to an
    upstream trace. Idempotent: applying twice is a no-op.
    """

    def wrapper(fn):
        if getattr(fn, "_hermes_traced", False):
            return fn

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            run_id = None
            parent = None
            try:
                tp = request.headers.get("traceparent") or request.headers.get("X-Traceparent")
                trace_id, parent_span = parse_traceparent(tp)
                if trace_id:
                    run_id = trace_id
                    parent = parent_span
            except Exception:
                pass
            cur = _cur_stack()
            if not run_id and cur:
                run_id = cur[-1]["run_id"]
                parent = cur[-1]["span_id"]
            if not run_id:
                run_id = _new_trace_id()
            span_obj = Span(name, run_id=run_id, parent=parent)
            try:
                span_obj.set_params({
                    "path": getattr(request, "path", ""),
                    "method": getattr(request, "method", ""),
                    "body": _scrub(request.get_json(silent=True) if request.method != "GET" else {}),
                    "query": _scrub(dict(request.args or {})),
                })
                span_obj.set_attribute("http.method", request.method)
                span_obj.set_attribute("http.path", request.path)
            except Exception:
                pass
            with _SpanCtx(span_obj):
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    span_obj.set_error(exc)
                    raise
                try:
                    body, status = _extract_status_and_body(result)
                    span_obj.set_attribute("http.status_code", status)
                    summary = _summarize_response_body(body)
                    if summary is not None:
                        span_obj.set_result(summary)
                    if status >= 400 and span_obj.get("status") == "running":
                        span_obj["status"] = "error"
                        span_obj["error"] = span_obj.get("error") or f"HTTP {status}"
                except Exception:
                    pass
                return result

        inner._hermes_traced = True
        return inner

    return wrapper


# Endpoint URL-rule patterns that get auto-wrapped when routes_trace is
# registered — covers every core action surface named in the feature spec.
_DEFAULT_WRAP_PATTERNS = (
    (re.compile(r"^/mouse/"), "coagent.mouse"),
    (re.compile(r"^/key(/|$)"), "coagent.key"),
    (re.compile(r"^/keyboard/"), "coagent.key"),
    (re.compile(r"^/type(/|$)"), "coagent.key"),
    (re.compile(r"^/uia(/|_|$)"), "coagent.uia"),
    (re.compile(r"^/browser/"), "coagent.browser"),
    (re.compile(r"^/browser_"), "coagent.browser"),
    (re.compile(r"^/process/"), "coagent.process"),
    (re.compile(r"^/agent/"), "coagent.agent"),
    (re.compile(r"^/hybrid_agent/"), "coagent.agent"),
    (re.compile(r"^/copilot/"), "coagent.copilot"),
)


def wrap_action_endpoints(app, patterns=None):
    """Post-registration hook: decorate view functions whose URL rule matches
    an action pattern with ``@trace_action``. Idempotent."""
    if patterns is None:
        patterns = _DEFAULT_WRAP_PATTERNS
    wrapped = 0
    for rule in list(app.url_map.iter_rules()):
        path = rule.rule
        span_name = None
        for pat, name in patterns:
            if pat.match(path):
                span_name = f"{name}:{path}"
                break
        if span_name is None:
            continue
        view_fn = app.view_functions.get(rule.endpoint)
        if view_fn is None or getattr(view_fn, "_hermes_traced", False):
            continue
        app.view_functions[rule.endpoint] = trace_action(span_name)(view_fn)
        wrapped += 1
    if wrapped:
        _console(f"[trace] wrapped {wrapped} action endpoints")
    return wrapped


def _list_runs():
    entries = []
    try:
        for p in TRACES_DIR.glob("*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append({
                "run_id": p.stem,
                "size": st.st_size,
                "modified": st.st_mtime,
            })
    except Exception:
        pass
    entries.sort(key=lambda e: e["modified"], reverse=True)
    return entries


def _load_run(run_id):
    safe = _safe_run_id(run_id)
    if not safe:
        return None
    path = TRACES_DIR / f"{safe}.jsonl"
    if not path.is_file():
        return None
    spans = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    spans.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    spans.sort(key=lambda s: s.get("start") or 0)
    return {"run_id": safe, "spans": spans}


@trace_bp.route("/trace/runs", methods=["GET"])
def route_trace_runs():
    return jsonify({"runs": _list_runs()[:MAX_RUNS_LISTED]})


@trace_bp.route("/trace/runs/<run_id>", methods=["GET"])
def route_trace_run(run_id):
    data = _load_run(run_id)
    if data is None:
        return jsonify({"error": "run not found"}), 404
    spans = data["spans"]
    steps = []
    for s in spans:
        steps.append({
            "span_id": s.get("span_id"),
            "parent_span_id": s.get("parent_span_id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "error": s.get("error"),
            "start": s.get("start"),
            "end": s.get("end"),
            "duration_ms": s.get("duration_ms"),
            "params": s.get("params"),
            "result": s.get("result"),
            "attributes": s.get("attributes") or {},
            "before_screenshot": s.get("before_screenshot"),
            "after_screenshot": s.get("after_screenshot"),
        })
    return jsonify({
        "run_id": data["run_id"],
        "count": len(steps),
        "started_at": steps[0].get("start") if steps else None,
        "finished_at": steps[-1].get("end") if steps else None,
        "steps": steps,
    })


@trace_bp.route("/trace/status", methods=["GET"])
def route_trace_status():
    tracer = _try_init_otlp()
    return jsonify({
        "otlp_enabled": bool(tracer),
        "otlp_endpoint": _OTLP_ENDPOINT or None,
        "service_name": _OTEL_SERVICE_NAME,
        "traces_dir": str(TRACES_DIR),
        "runs": len(_list_runs()),
    })


def register_routes(app, state, require_auth):
    app.register_blueprint(trace_bp)
    _wrap_registered_blueprint_routes(app, trace_bp.name, require_auth)
    wrap_action_endpoints(app)
    try:
        state.trace = {
            "otlp_enabled": bool(_try_init_otlp()),
            "traces_dir": str(TRACES_DIR),
        }
    except Exception:
        pass
