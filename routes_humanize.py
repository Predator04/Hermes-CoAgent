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


_SHIFT_CHARS = frozenset("~!@#$%^&*()_+{}|:\"<>?")

_KEY_NEIGHBOURS = {
    "a": "s", "s": "a", "d": "f", "f": "d", "g": "f", "h": "g", "j": "k",
    "k": "j", "l": "k", "q": "w", "w": "q", "e": "r", "r": "e", "t": "r",
    "y": "t", "u": "y", "i": "o", "o": "i", "p": "o", "z": "x", "x": "z",
    "c": "v", "v": "c", "b": "v", "n": "m", "m": "n",
}


def humanized_keystrokes(text, wpm=45.0, mistake_rate=0.0, seed=None):
    """Plan a human-like keystroke cadence for ``text``.

    Returns a list of steps: {"key", "delay_ms", "shift", "correction"}.
    Corrections are a mistyped neighbour key followed by a backspace step.
    Deterministic when ``seed`` is given. Per-key delay is Gaussian jitter
    around a base rate derived from ``wpm`` (chars/min ~= 5 * wpm), with
    longer pauses on whitespace/punctuation and a press-hold penalty on shift
    chords.
    """
    rng = random.Random(seed)
    wpm = max(10.0, min(float(wpm), 300.0))
    mistake_rate = max(0.0, min(float(mistake_rate), 0.25))
    chars_per_sec = wpm * 5.0 / 60.0
    base_ms = 1000.0 / max(0.1, chars_per_sec)

    steps = []
    for ch in text:
        delay = max(15.0, base_ms + rng.gauss(0.0, base_ms * 0.30))
        if ch in " \t":
            delay *= 1.8
        elif ch in ",.;:!?\n":
            delay *= 2.2
        shift = ch.isupper() or ch in _SHIFT_CHARS
        if shift:
            delay += rng.uniform(30.0, 90.0)

        lowered = ch.lower()
        if (mistake_rate > 0 and ch.isalnum() and lowered in _KEY_NEIGHBOURS
                and rng.random() < mistake_rate):
            wrong = _KEY_NEIGHBOURS[lowered]
            wrong = wrong.upper() if ch.isupper() else wrong
            steps.append({"key": wrong, "delay_ms": round(delay, 2),
                          "shift": shift, "correction": False})
            steps.append({"key": "backspace",
                          "delay_ms": round(rng.uniform(120.0, 320.0), 2),
                          "shift": False, "correction": True})

        steps.append({"key": ch, "delay_ms": round(delay, 2),
                      "shift": shift, "correction": False})
    return steps


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

    @app.route("/keyboard/humanized_type", methods=["POST"])
    @require_auth
    def route_humanized_type():
        body = _json_body()
        text = body.get("text")
        if text is None:
            return jsonify({"ok": False, "error": "Missing required field: text"}), 400
        if not isinstance(text, str):
            return jsonify({"ok": False, "error": "text must be a string"}), 400
        if len(text) > 10000:
            return jsonify({"ok": False, "error": "text too long (max 10000 chars)"}), 400

        try:
            wpm = float(body.get("wpm", 45))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "wpm must be numeric"}), 400
        wpm = max(10.0, min(wpm, 300.0))

        try:
            mistake_rate = float(body.get("mistake_rate", 0.0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "mistake_rate must be numeric"}), 400
        mistake_rate = max(0.0, min(mistake_rate, 0.25))

        seed = body.get("seed")
        if seed is not None and not isinstance(seed, (int, str, type(None))):
            return jsonify({"ok": False, "error": "seed must be int, str, or null"}), 400

        plan = humanized_keystrokes(text, wpm=wpm, mistake_rate=mistake_rate, seed=seed)
        estimated_ms = round(sum(s["delay_ms"] for s in plan), 1)

        if body.get("dry_run"):
            return jsonify({
                "ok": True,
                "dry_run": True,
                "chars": len(text),
                "steps": len(plan),
                "wpm": wpm,
                "mistake_rate": mistake_rate,
                "estimated_ms": estimated_ms,
                "plan": plan,
            })

        if state is not None and getattr(state, "emergency_stop", False):
            return jsonify({"ok": False, "error": "Emergency stop is engaged",
                            "code": "EMERGENCY_STOP"}), 503

        import time as _time
        try:
            import pyautogui as _pa
        except ImportError:
            return jsonify({"ok": False, "error": "pyautogui unavailable"}), 501
        try:
            _pa.FAILSAFE = False
        except Exception:
            pass

        sent = 0
        aborted = False
        for step in plan:
            if state is not None and getattr(state, "emergency_stop", False):
                aborted = True
                break
            try:
                if step["key"] == "backspace":
                    _pa.press("backspace")
                else:
                    _pa.write(step["key"])
                sent += 1
            except Exception as exc:
                _LOGGER.warning("humanized_type keystroke failed: %s", exc)
            _time.sleep(min(step["delay_ms"], 500) / 1000.0)

        if aborted:
            return jsonify({
                "ok": False,
                "error": "Emergency stop engaged mid-typing",
                "code": "EMERGENCY_STOP",
                "chars": len(text),
                "steps": len(plan),
                "sent": sent,
                "wpm": wpm,
                "mistake_rate": mistake_rate,
                "estimated_ms": estimated_ms,
            }), 503

        return jsonify({
            "ok": True,
            "chars": len(text),
            "steps": len(plan),
            "sent": sent,
            "wpm": wpm,
            "mistake_rate": mistake_rate,
            "estimated_ms": estimated_ms,
        })

    _LOGGER.info("Humanized mouse routes registered")
