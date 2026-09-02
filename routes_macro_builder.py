"""Natural-language macro builder (issue #2).

Turns a plain-text list of steps into a structured macro of actions that can be
fed to the recorder/replay engine. The parser is a pure function and fully
unit-tested. Grammar (one step per line or ';'-separated):

  click X,Y            double click X,Y        right click X,Y
  move X,Y             drag X,Y -> X,Y
  type <text>          press <key[+key]>       hotkey ctrl+c
  wait <n> ms|s        scroll up|down <n>
Lines starting with '#' are comments.
"""
import logging
import re

from flask import Blueprint, jsonify

from shared import _json_body

_LOGGER = logging.getLogger(__name__)
macro_builder_bp = Blueprint("macro_builder", __name__)

_COORD = r"(-?\d+)\s*,\s*(-?\d+)"


def _parse_step(line):
    """Parse one step -> (action_dict|None, warning|None)."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None, None
    low = s.lower()

    m = re.match(rf"^(double\s+click|double-click|doubleclick)\s+{_COORD}$", low)
    if m:
        return {"action": "double_click", "x": int(m.group(2)), "y": int(m.group(3))}, None
    m = re.match(rf"^right\s*click\s+{_COORD}$", low)
    if m:
        return {"action": "right_click", "x": int(m.group(1)), "y": int(m.group(2))}, None
    m = re.match(rf"^click\s+{_COORD}$", low)
    if m:
        return {"action": "click", "x": int(m.group(1)), "y": int(m.group(2))}, None
    m = re.match(rf"^move\s+{_COORD}$", low)
    if m:
        return {"action": "move", "x": int(m.group(1)), "y": int(m.group(2))}, None
    m = re.match(rf"^drag\s+{_COORD}\s*(?:->|to)\s*{_COORD}$", low)
    if m:
        return {"action": "drag", "x1": int(m.group(1)), "y1": int(m.group(2)),
                "x2": int(m.group(3)), "y2": int(m.group(4))}, None
    m = re.match(r"^type\s+(.+)$", s, re.IGNORECASE)
    if m:
        text = m.group(1)
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        return {"action": "type", "text": text}, None
    m = re.match(r"^(?:press|hotkey|key)\s+([a-z0-9\+\s]+)$", low)
    if m:
        keys = [k.strip() for k in re.split(r"[+\s]+", m.group(1)) if k.strip()]
        return {"action": "hotkey", "keys": keys}, None
    m = re.match(r"^wait\s+(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?|milliseconds?)?$", low)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "ms")
        ms = val if unit.startswith("m") else val * 1000
        return {"action": "wait", "ms": int(ms)}, None
    m = re.match(r"^scroll\s+(up|down)\s+(\d+)$", low)
    if m:
        amt = int(m.group(2))
        return {"action": "scroll", "dy": amt if m.group(1) == "down" else -amt}, None
    return None, f"unrecognized step: {s!r}"


def build_macro(text):
    """Parse multi-line / ';'-separated NL text into {steps, warnings}."""
    raw_lines = []
    for chunk in (text or "").splitlines():
        # Split by semicolons, but respect quoted strings
        parts = []
        current = []
        in_quote = None
        for ch in chunk:
            if ch in ('"', "'") and in_quote is None:
                in_quote = ch
                current.append(ch)
            elif ch == in_quote:
                in_quote = None
                current.append(ch)
            elif ch == ';' and in_quote is None:
                parts.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current).strip())
        raw_lines.extend(parts)
    steps, warnings = [], []
    for line in raw_lines:
        action, warn = _parse_step(line)
        if action:
            steps.append(action)
        elif warn:
            warnings.append(warn)
    return {"steps": steps, "warnings": warnings}


def register_routes(app, state, require_auth):
    @app.route("/macro/build", methods=["POST"])
    @require_auth
    def route_macro_build():
        body = _json_body()
        text = body.get("text")
        if not isinstance(text, str) or not text:
            return jsonify({"ok": False, "error": "Missing required field: text"}), 400
        result = build_macro(text)
        return jsonify({"ok": True, "step_count": len(result["steps"]), **result})

    _LOGGER.info("Macro builder routes registered")
