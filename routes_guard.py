"""Prompt-injection & untrusted-content defense.

A fast, rule-based detector that flags imperative / role-shifting / exfiltration
/ destructive content *before* it re-enters the agent context. Web pages,
downloaded files, OCR'd screen text, clipboard contents and MCP tool results
can all whisper instructions into the agent loop; this module gives callers a
single `sanitize()` entry point that neutralizes flagged content and exposes a
`/guard/scan` endpoint for inspection.

Endpoints:
    POST /guard/scan      — scan text, return risk verdict + matched rules
    POST /guard/sanitize  — wrap/neutralize flagged content
    GET  /guard/rules     — list active rules
"""

import re
import secrets
import unicodedata

from flask import jsonify

from shared import _json_body, _log

# (rule_name, severity, compiled regex). Weights: low=1, medium=2, high=3, critical=5.
RULES = [
    ("role_shift", "critical", re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions", re.I)),
    ("role_shift", "critical", re.compile(r"you\s+are\s+now\s+(an?\s+)?(a\s+different\s+)?(assistant|agent|ai|system|jailbroken)", re.I)),
    ("role_shift", "high", re.compile(r"you\s+are\s+no\s+longer\b", re.I)),
    ("role_shift", "high", re.compile(r"do\s+not\s+(follow|obey)\s+(your\s+)?(instructions|guidelines|rules|prompt)", re.I)),
    ("role_shift", "high", re.compile(r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+instructions", re.I)),
    ("token_exfil", "critical", re.compile(r"(reveal|print|send|share|output|exfiltrate|leak)\s+(me\s+)?(your\s+)?(api\s*key|token|secret|credential|password|private\s*key)", re.I)),
    ("token_exfil", "critical", re.compile(r"(what\s+is|show\s+me)\s+(your\s+)?(api\s*key|token|secret|credential|password)", re.I)),
    ("destructive", "critical", re.compile(r"\brm\s+-rf\b", re.I)),
    ("destructive", "critical", re.compile(r"\b(format|wipe)\s+[a-z]:\\", re.I)),
    ("destructive", "critical", re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.I)),
    ("destructive", "high", re.compile(r"\b(shutdown|reboot|power\s*off)\b", re.I)),
    ("destructive", "high", re.compile(r"\bdel(ete)?\s+((/f|/q)\s+)?.*(all|everything)", re.I)),
    ("goal_change", "high", re.compile(r"(your\s+(new\s+)?goal|your\s+task)\s+is\s+now", re.I)),
    ("goal_change", "high", re.compile(r"forget\s+(everything\s+)?(about\s+)?(the\s+)?(previous|prior|original|above)", re.I)),
    ("bypass_consent", "high", re.compile(r"without\s+(asking|permission|confirmation|telling)", re.I)),
    ("bypass_consent", "high", re.compile(r"do\s+not\s+ask\s+(for\s+)?(permission|confirmation|approval)", re.I)),
    ("hidden_text", "medium", re.compile(r"(system\s+prompt|developer\s+message)\s*(:|=|says)", re.I)),
    ("url_drive", "medium", re.compile(r"\b(visit|open|download|navigate\s+to)\s+https?://", re.I)),
]

SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 5}

_MAX_INPUT = 65536
_MAX_MATCHES = 500


def _scan(text):
    """Return (matches, score, risk)."""
    if not isinstance(text, str) or not text:
        return [], 0, "none"
    if len(text) > _MAX_INPUT:
        text = text[:_MAX_INPUT]
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"[\u200b-\u200d\u2060\ufeff\u00ad]", "", normalized)
    matches = []
    for name, severity, regex in RULES:
        for m in regex.finditer(normalized):
            if len(matches) >= _MAX_MATCHES:
                break
            matches.append({
                "rule": name,
                "severity": severity,
                "match": m.group(0)[:200],
                "start": m.start(),
            })
        if len(matches) >= _MAX_MATCHES:
            break
    score = sum(SEVERITY_WEIGHT.get(m["severity"], 1) for m in matches)
    if score >= 5:
        risk = "critical"
    elif score >= 3:
        risk = "high"
    elif score >= 2:
        risk = "medium"
    elif score >= 1:
        risk = "low"
    else:
        risk = "none"
    return matches, score, risk


def sanitize(text):
    """Neutralize flagged content by wrapping it in a low-trust annotation.

    Returns a dict with the (possibly wrapped) text plus risk metadata, so other
    modules can call this directly when piping untrusted content back into the
    agent loop.
    """
    matches, score, risk = _scan(text)
    if risk == "none":
        return {"risk": "none", "score": 0, "flagged": False, "text": text, "matches": []}
    nonce = secrets.token_hex(8)
    open_marker = "[UNTRUSTED CONTENT %s — risk:%s — verify before acting]" % (nonce, risk)
    close_marker = "[END UNTRUSTED CONTENT %s]" % nonce
    neutralized = "%s\n%s\n%s" % (open_marker, text, close_marker)
    return {"risk": risk, "score": score, "flagged": True, "text": neutralized, "matches": matches}


def register_routes(app, state, require_auth):
    @app.route("/guard/scan", methods=["POST"])
    @require_auth
    def route_guard_scan():
        data = _json_body() or {}
        text = data.get("text") or data.get("content") or ""
        matches, score, risk = _scan(text)
        _log("guard: scan -> risk=%s score=%s matches=%d" % (risk, score, len(matches)))
        return jsonify({"risk": risk, "score": score, "flagged": risk != "none", "matches": matches})

    @app.route("/guard/sanitize", methods=["POST"])
    @require_auth
    def route_guard_sanitize():
        data = _json_body() or {}
        text = data.get("text") or data.get("content") or ""
        result = sanitize(text)
        _log("guard: sanitize -> risk=%s" % result["risk"])
        return jsonify(result)

    @app.route("/guard/rules", methods=["GET"])
    @require_auth
    def route_guard_rules():
        seen = [{"rule": name, "severity": severity, "pattern": regex.pattern}
                for name, severity, regex in RULES]
        return jsonify({"rules": seen, "count": len(seen)})
