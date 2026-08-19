"""Humanized mouse movement (issue #9).

Generates a cubic-Bezier cursor path with a slightly randomized arc and
variable (ease-in/ease-out + jitter) timing so movement looks organic rather
than a straight teleport. The path generator is a pure function and fully
unit-tested; the endpoint drives the existing mouse backend when present and
otherwise returns the computed path (dry run) so it works headless too.
"""
import logging
import math
import random

from flask import Blueprint, jsonify

from shared import _json_body

_LOGGER = logging.getLogger(__name__)
humanize_bp = Blueprint("humanize", __name__)


def _bezier_point(p0, p1, p2, p3, t):
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    x = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]
    y = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]
    return x, y


def _ease(t):
    # smoothstep ease-in/ease-out
    return t * t * (3 - 2 * t)


def humanized_path(start, end, steps=40, duration_ms=600, curve=0.18,
                   jitter=1.0, seed=None):
    """Return a list of {"x","y","delay_ms"} points from start to end.

    Deterministic when ``seed`` is provided. Control points are offset
    perpendicular to the travel vector to create a natural arc; per-step delays
    follow an eased velocity profile with small random jitter.
    """
    rng = random.Random(seed)
    steps = max(2, int(steps))
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])

    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy) or 1.0
    # perpendicular unit vector
    px, py = -dy / dist, dx / dist
    # two control points at 1/3 and 2/3 with opposing perpendicular offsets
    amp = curve * dist
    off1 = amp * rng.uniform(0.5, 1.0)
    off2 = -amp * rng.uniform(0.5, 1.0)
    c1 = (sx + dx / 3 + px * off1, sy + dy / 3 + py * off1)
    c2 = (sx + 2 * dx / 3 + px * off2, sy + 2 * dy / 3 + py * off2)

    points = []
    total_weight = 0.0
    raw = []
    for i in range(steps):
        t = i / (steps - 1)
        et = _ease(t)
        x, y = _bezier_point((sx, sy), c1, c2, (ex, ey), et)
        if 0 < i < steps - 1:
            x += rng.uniform(-jitter, jitter)
            y += rng.uniform(-jitter, jitter)
        raw.append((x, y))
    # velocity profile: slow-fast-slow => delay larger at the ends
    for i in range(steps):
        t = i / (steps - 1)
        speed = math.sin(math.pi * t)  # 0 at ends, 1 in middle
        weight = 1.0 / (0.15 + speed)  # inverse => longer delay when slow
        weight *= rng.uniform(0.9, 1.1)
        total_weight += weight
        raw[i] = (raw[i][0], raw[i][1], weight)
    for x, y, weight in raw:
        delay = duration_ms * (weight / total_weight)
        points.append({"x": int(round(x)), "y": int(round(y)),
                       "delay_ms": round(delay, 2)})
    # guarantee exact endpoint
    points[-1]["x"], points[-1]["y"] = int(round(ex)), int(round(ey))
    return points


def _current_cursor():
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)
    except Exception:
        return None


def _move_to(x, y):
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        return True
    except Exception:
        return False


def register_routes(app, state, require_auth):
    @app.route("/mouse/humanized_move", methods=["POST"])
    @require_auth
    def route_humanized_move():
        body = _json_body()
        if "x" not in body or "y" not in body:
            return jsonify({"ok": False, "error": "Missing required field: x and y"}), 400
        try:
            tx, ty = int(body["x"]), int(body["y"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "x and y must be integers"}), 400
        try:
            steps = int(body.get("steps", 40))
            duration_ms = float(body.get("duration_ms", 600))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "steps and duration_ms must be numeric"}), 400
        steps = max(2, min(steps, 500))
        duration_ms = max(0.0, min(duration_ms, 10000.0))
        seed = body.get("seed")
        # Coerce seed to valid type to avoid TypeError in random.Random()
        if seed is not None and not isinstance(seed, (int, str, type(None))):
            return jsonify({"ok": False, "error": "seed must be int, str, or null"}), 400
        start = body.get("start")
        if not start:
            start = _current_cursor() or (tx, ty)
        else:
            # Validate start is a valid coordinate pair
            if not isinstance(start, (list, tuple)) or len(start) != 2:
                return jsonify({"ok": False, "error": "start must be [x, y]"}), 400
            try:
                start = (float(start[0]), float(start[1]))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "start coordinates must be numeric"}), 400

        path = humanized_path(start, (tx, ty), steps=steps,
                              duration_ms=duration_ms, seed=seed)

        import time
        moved = 0
        for pt in path:
            if _move_to(pt["x"], pt["y"]):
                moved += 1
                time.sleep(min(pt["delay_ms"], 100) / 1000.0)
        return jsonify({
            "ok": True,
            "target": {"x": tx, "y": ty},
            "steps": len(path),
            "moved": moved,
            "dry_run": moved == 0,
            "path": path if body.get("return_path") else path[:1] + path[-1:],
        })

    _LOGGER.info("Humanized mouse routes registered")
