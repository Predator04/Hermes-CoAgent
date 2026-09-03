"""Prometheus-style metrics endpoint for Hermes CoAgent."""

import logging
import os
import time
from collections import Counter

from flask import Blueprint, Response, g, request

from shared import _sse_clients, _sse_lock


metrics_bp = Blueprint("metrics", __name__)
_LOGGER = logging.getLogger(__name__)

REQUESTS = Counter()
ERRORS = Counter()
LATENCY_HISTOGRAM = [
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    float("inf"),
]
LATENCY_BUCKETS = Counter()
LATENCY_COUNT = Counter()
LATENCY_SUM = Counter()

import threading

_METRICS_LOCK = threading.Lock()


def _debug_failure(context, exc):
    _LOGGER.debug("%s failed: %s: %s", context, type(exc).__name__, exc, exc_info=True)


def _lock():
    return _METRICS_LOCK


def _bucket_label(bucket):
    if bucket == float("inf"):
        return "+Inf"
    return f"{bucket:g}"


def _le_sort_value(le):
    if le == "+Inf":
        return float("inf")
    try:
        return float(le)
    except (TypeError, ValueError):
        return float("inf")


def _label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace('"', '\\"')


def _route_path():
    try:
        if request.url_rule and request.url_rule.rule:
            return request.url_rule.rule
    except (AttributeError, RuntimeError) as exc:
        _debug_failure("metrics route path lookup", exc)
    # Unmatched paths (404s) are attacker-controlled; never use them as a
    # label or every probe would grow the counters without bound.
    return "<unmatched>"


def _memory_rss_bytes():
    try:
        import psutil
    except ImportError as exc:
        _debug_failure("metrics psutil import", exc)
        psutil = None

    if psutil is not None:
        try:
            return int(psutil.Process(os.getpid()).memory_info().rss)
        except Exception as exc:
            # psutil.NoSuchProcess / AccessDenied / TimeoutExpired inherit from
            # psutil.Error (not OSError), so a broad guard is required here to
            # fall through to the procfs/Win32 backends.
            _debug_failure("metrics psutil RSS lookup", exc)

    proc_status = "/proc/self/status"
    try:
        with open(proc_status, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except (OSError, ValueError) as exc:
        _debug_failure("metrics procfs RSS lookup", exc)

    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return int(counters.WorkingSetSize)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        _debug_failure("metrics Win32 RSS lookup", exc)

    return 0


def _active_sse_connections():
    total = 0
    try:
        with _sse_lock:
            total += len(_sse_clients)
    except (AttributeError, RuntimeError) as exc:
        _debug_failure("metrics shared SSE count", exc)

    try:
        from routes_agent import ACTIVE_STREAMS, _streams_lock

        with _streams_lock:
            for stream_state in ACTIVE_STREAMS.values():
                total += int(stream_state.get("connections", 0) or 0)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as exc:
        _debug_failure("metrics agent stream count", exc)

    try:
        from routes_stream import _active_stream_count

        total += int(_active_stream_count())
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as exc:
        _debug_failure("metrics screen stream count", exc)

    return total


def _format_counter(metric, samples, label_names):
    lines = []
    for key, value in sorted(samples.items(), key=lambda item: item[0]):
        labels = ",".join(
            f'{name}="{_label(part)}"' for name, part in zip(label_names, key)
        )
        lines.append(f"{metric}{{{labels}}} {int(value)}")
    return lines


def _render_metrics():
    lines = [
        "# HELP coagent_requests_total Total HTTP requests",
        "# TYPE coagent_requests_total counter",
    ]

    with _lock():
        requests_snapshot = Counter(REQUESTS)
        errors_snapshot = Counter(ERRORS)
        buckets_snapshot = Counter(LATENCY_BUCKETS)
        counts_snapshot = Counter(LATENCY_COUNT)
        sums_snapshot = Counter(LATENCY_SUM)

    lines.extend(
        _format_counter(
            "coagent_requests_total",
            requests_snapshot,
            ("method", "path", "status"),
        )
    )
    lines.extend(
        [
            "# HELP coagent_request_errors_total Total HTTP error responses",
            "# TYPE coagent_request_errors_total counter",
        ]
    )
    lines.extend(
        _format_counter(
            "coagent_request_errors_total",
            errors_snapshot,
            ("method", "path", "status"),
        )
    )

    lines.extend(
        [
            "# HELP coagent_request_duration_seconds Request duration",
            "# TYPE coagent_request_duration_seconds histogram",
        ]
    )
    # Prometheus cumulative histograms must emit every configured bucket for
    # every series that has an observation (missing `le` lines are rejected by
    # promtool). Emit all buckets in ascending order, defaulting unobserved
    # buckets to 0.
    for key in sorted(counts_snapshot.keys()):
        method, path, status = key
        base_labels = (
            f'method="{_label(method)}",'
            f'path="{_label(path)}",'
            f'status="{_label(status)}"'
        )
        for bucket in LATENCY_HISTOGRAM:
            le = _bucket_label(bucket)
            value = int(buckets_snapshot.get(key + (le,), 0))
            lines.append(
                f'coagent_request_duration_seconds_bucket{{{base_labels},le="{le}"}} {value}'
            )
        lines.append(
            f'coagent_request_duration_seconds_count{{{base_labels}}} {int(counts_snapshot.get(key, 0))}'
        )
        lines.append(
            f'coagent_request_duration_seconds_sum{{{base_labels}}} {sums_snapshot.get(key, 0.0):.9f}'
        )

    lines.extend(
        [
            "# HELP coagent_active_connections Current SSE/stream connections",
            "# TYPE coagent_active_connections gauge",
            f"coagent_active_connections {_active_sse_connections()}",
            "# HELP coagent_memory_rss_bytes Process memory in bytes",
            "# TYPE coagent_memory_rss_bytes gauge",
            f"coagent_memory_rss_bytes {_memory_rss_bytes()}",
        ]
    )
    return "\n".join(lines) + "\n"


@metrics_bp.route("/metrics", methods=["GET"])
def route_metrics():
    return Response(_render_metrics(), mimetype="text/plain; version=0.0.4")


def register_routes(app, state, require_auth):
    @app.before_request
    def _metrics_before_request():
        if request.endpoint == "metrics.route_metrics":
            return None
        g._metrics_start_time = time.perf_counter()
        return None

    @app.after_request
    def _metrics_after_request(response):
        if request.endpoint == "metrics.route_metrics":
            return response
        try:
            started = getattr(g, "_metrics_start_time", None)
            # Use an explicit None check: perf_counter() is never None, but a
            # short-circuited before_request leaves started unset and must not
            # record a spurious 0.0s latency sample in the smallest bucket.
            duration = max(0.0, time.perf_counter() - started) if started is not None else None
            method = request.method or "UNKNOWN"
            path = _route_path()
            status = str(response.status_code)
            request_key = (method, path, status)
            with _lock():
                REQUESTS[request_key] += 1
                if response.status_code >= 400:
                    ERRORS[request_key] += 1
                if duration is not None:
                    LATENCY_COUNT[request_key] += 1
                    LATENCY_SUM[request_key] += duration
                    for bucket in LATENCY_HISTOGRAM:
                        if duration <= bucket:
                            LATENCY_BUCKETS[request_key + (_bucket_label(bucket),)] += 1
        except Exception as exc:
            _debug_failure("metrics after_request accounting", exc)
        return response

    # The metrics endpoint exposes internal telemetry (route surface, error
    # rates, memory RSS, live stream counts) and must require auth like every
    # other route when auth is enabled. Wrap BEFORE registering the blueprint so
    # there is never a window where /metrics is reachable unauthenticated.
    if require_auth is not None:
        for endpoint, view_func in list(metrics_bp.view_functions.items()):
            if getattr(view_func, "_hermes_auth_wrapped", False):
                continue
            wrapped = require_auth(view_func)
            wrapped._hermes_auth_wrapped = True
            metrics_bp.view_functions[endpoint] = wrapped
    app.register_blueprint(metrics_bp)
