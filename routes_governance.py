"""Automation Governance Layer for Hermes CoAgent.

Provides app/domain allowlists & denylists, action budgets (per-hour sliding
window + per-goal cumulative caps), and automatic secret/PII redaction for
authenticated automation actions.

Policy is persisted to ``COAGENT_DIR / "governance.json"`` and audit entries
to ``COAGENT_DIR / "governance_audit.jsonl"``. All operations are thread-safe
and default to permissive behavior so enabling the module never breaks a
running server.
"""

import copy
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import jsonify, request

from shared import COAGENT_DIR, _log


DEFAULT_POLICY = {
    "enabled": False,
    # "normal" | "observe" — observe mode blocks mutating endpoints (file
    # writes/deletes, process start/kill, registry/macro/clipboard writes,
    # power, installs) while keeping every read endpoint live: an autonomous
    # run can *see* the desktop without being able to *touch* the filesystem.
    "mode": "normal",
    # Per-path write allowlist. Empty list = unrestricted (backward compatible).
    # When non-empty, /file/write is refused for any target outside these roots.
    "write_roots": [],
    "apps": {
        "mode": "allow",
        "allowlist": [],
        "denylist": [],
    },
    "domains": {
        "mode": "allow",
        "allowlist": [],
        "denylist": [],
    },
    "budgets": {
        "enabled": False,
        "per_hour": {
            "click": 500,
            "keystroke": 2000,
            "type": 500,
            "navigate": 200,
            "process_start": 50,
            "window_activate": 100,
            "scroll": 500,
            "screenshot": 200,
        },
        "per_goal": {
            "click": 200,
            "keystroke": 800,
            "type": 200,
            "navigate": 100,
            "process_start": 25,
            "window_activate": 50,
            "scroll": 200,
            "screenshot": 100,
        },
    },
    "redact": {
        "enabled": True,
    },
}

_BUDGET_ACTIONS = (
    "click",
    "keystroke",
    "type",
    "navigate",
    "process_start",
    "window_activate",
    "scroll",
    "screenshot",
)

_POLICY_PATH = COAGENT_DIR / "governance.json"
_AUDIT_PATH = COAGENT_DIR / "governance_audit.jsonl"
_AUDIT_MAX_MEM = 1000
_REDACT_MAX_CHARS = 1_000_000

# Endpoints blocked while observe mode is active. Prefixed precisely so read
# endpoints (/file/read, /file/list, /macro/list, /process/list, ...) stay live.
_OBSERVE_BLOCKED_PREFIXES = (
    "/file/write",
    "/file/delete",
    "/file/move",
    "/file/copy",
    "/file/rename",
    "/process/start",
    "/process/kill",
    "/process/priority",
    "/clipboard/set",
    "/clipboard/history/set",
    "/clipboard/clear",
    "/power/sleep",
    "/power/shutdown",
    "/power/restart",
    "/power/lock",
    "/registry",
    "/macro/build",
    "/macro/rec/start",
    "/macro/rec/stop",
    "/macro/delete",
    "/macro/replay",
    "/macro/save",
    "/macro/run",
    "/macro/record",
    "/install",
    "/uninstall",
)

# Pre-compiled redaction patterns. Order matters: broad multi-line matches
# (private keys, JWTs) run before narrower ones so we don't destroy the block
# structure with a partial replacement.
_REDACT_PATTERNS = [
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[^\"]*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED]",
    ),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        "[REDACTED]",
    ),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "[REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "[REDACTED]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
    (
        re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"((?:password|passwd|pwd|secret|api_key|apikey|token)[\"']?\s*[:=]\s*[\"']?)([^\s\"',&]+)",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED]"),
]


def _deep_merge(base, overlay):
    """Recursively merge ``overlay`` into a deep copy of ``base``.

    Dict-valued keys are merged; every other type is replaced wholesale.
    Non-dict overlays are ignored (returns a copy of base).
    """
    out = copy.deepcopy(base)
    if not isinstance(overlay, dict):
        return out
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _now_hour_bucket():
    return int(time.time() // 3600)


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


class _Governor:
    """Thread-safe policy enforcement, budget tracking, audit, and redaction."""

    def __init__(self):
        self._lock = threading.RLock()
        self._policy = copy.deepcopy(DEFAULT_POLICY)
        self._audit = deque(maxlen=_AUDIT_MAX_MEM)
        self._goal_id = None
        self._hour_bucket = _now_hour_bucket()
        self._hour_counts = {a: 0 for a in _BUDGET_ACTIONS}
        self._goal_counts = {a: 0 for a in _BUDGET_ACTIONS}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self):
        with self._lock:
            try:
                if _POLICY_PATH.exists():
                    raw = _POLICY_PATH.read_text(encoding="utf-8")
                    loaded = json.loads(raw) if raw.strip() else {}
                    if isinstance(loaded, dict):
                        merged = _deep_merge(DEFAULT_POLICY, loaded)
                        if self._validate(merged):
                            _log("[governance] loaded policy failed validation, using defaults")
                            self._policy = copy.deepcopy(DEFAULT_POLICY)
                        else:
                            self._policy = merged
                    else:
                        self._policy = copy.deepcopy(DEFAULT_POLICY)
                else:
                    self._policy = copy.deepcopy(DEFAULT_POLICY)
            except (OSError, ValueError, TypeError) as e:
                _log(f"[governance] load failed, using defaults: {e}")
                self._policy = copy.deepcopy(DEFAULT_POLICY)
            return copy.deepcopy(self._policy)

    def save(self, policy):
        with self._lock:
            try:
                tmp = _POLICY_PATH.with_suffix(".json.tmp")
                data = json.dumps(policy, indent=2, ensure_ascii=False)
                tmp.write_text(data, encoding="utf-8")
                os.replace(str(tmp), str(_POLICY_PATH))
            except (OSError, TypeError, ValueError) as e:
                _log(f"[governance] save failed: {e}")

    # ------------------------------------------------------------------
    # Policy read / write
    # ------------------------------------------------------------------
    def get_policy(self):
        with self._lock:
            return copy.deepcopy(self._policy)

    def _validate(self, policy):
        errors = []
        if not isinstance(policy, dict):
            return ["policy must be a JSON object"]
        allowed_top = set(DEFAULT_POLICY.keys())
        for k in policy.keys():
            if k not in allowed_top:
                errors.append(f"unknown top-level key: {k}")

        for section in ("apps", "domains"):
            sec = policy.get(section)
            if sec is None:
                continue
            if not isinstance(sec, dict):
                errors.append(f"{section} must be an object")
                continue
            if "mode" in sec and sec["mode"] not in ("allow", "deny"):
                errors.append(
                    f"{section}.mode must be 'allow' or 'deny', got {sec['mode']!r}"
                )
            for key in ("allowlist", "denylist"):
                if key in sec and not isinstance(sec[key], list):
                    errors.append(f"{section}.{key} must be a list")

        mode = policy.get("mode")
        if mode is not None and mode not in ("normal", "observe"):
            errors.append(f"mode must be 'normal' or 'observe', got {mode!r}")

        write_roots = policy.get("write_roots")
        if write_roots is not None:
            if not isinstance(write_roots, list):
                errors.append("write_roots must be a list")
            else:
                for root in write_roots:
                    if not isinstance(root, str) or not root.strip():
                        errors.append("write_roots entries must be non-empty strings")

        budgets = policy.get("budgets")
        if budgets is not None:
            if not isinstance(budgets, dict):
                errors.append("budgets must be an object")
            else:
                if "enabled" in budgets and not isinstance(budgets["enabled"], bool):
                    errors.append("budgets.enabled must be a boolean")
                for scope in ("per_hour", "per_goal"):
                    caps = budgets.get(scope)
                    if caps is None:
                        continue
                    if not isinstance(caps, dict):
                        errors.append(f"budgets.{scope} must be an object")
                        continue
                    for a, v in caps.items():
                        if isinstance(v, bool) or not isinstance(v, (int, float)):
                            errors.append(f"budgets.{scope}.{a} must be numeric")
                        elif v < 0:
                            errors.append(f"budgets.{scope}.{a} must be non-negative")

        redact = policy.get("redact")
        if redact is not None:
            if not isinstance(redact, dict):
                errors.append("redact must be an object")
            elif "enabled" in redact and not isinstance(redact["enabled"], bool):
                errors.append("redact.enabled must be a boolean")

        return errors

    def update_policy(self, partial):
        with self._lock:
            if not isinstance(partial, dict):
                return copy.deepcopy(self._policy), ["partial policy must be a JSON object"]
            errors = self._validate(partial)
            if errors:
                # Never merge/save a policy that fails validation — otherwise
                # malformed input silently corrupts the persisted state.
                return copy.deepcopy(self._policy), errors
            merged = _deep_merge(self._policy, partial)
            self._policy = merged
            self.save(merged)
            return copy.deepcopy(merged), errors

    def reset_policy(self):
        with self._lock:
            self._policy = copy.deepcopy(DEFAULT_POLICY)
            self.save(self._policy)
            return copy.deepcopy(self._policy)

    # ------------------------------------------------------------------
    # App / URL checks
    # ------------------------------------------------------------------
    def check_app(self, app_name):
        with self._lock:
            if not self._policy.get("enabled"):
                return (True, "")
            if not app_name:
                return (True, "")
            apps = self._policy.get("apps") or {}
            mode = apps.get("mode", "allow")
            allowlist = {str(x).lower() for x in (apps.get("allowlist") or [])}
            denylist = {str(x).lower() for x in (apps.get("denylist") or [])}
            try:
                raw = str(app_name).strip()
            except Exception:
                return (True, "")
            basename = os.path.basename(raw).lower()
            candidates = {basename, raw.lower()}
            # Denylist wins in BOTH modes.
            if candidates & denylist:
                label = basename or raw
                return (False, f"app denied by policy: {label}")
            if mode == "deny":
                if candidates & allowlist:
                    return (True, "")
                label = basename or raw
                return (False, f"app denied by policy: {label}")
            # allow-mode: not denied → permitted.
            return (True, "")

    def check_url(self, url):
        with self._lock:
            if not self._policy.get("enabled"):
                return (True, "")
            if not url:
                return (True, "")
            domains = self._policy.get("domains") or {}
            mode = domains.get("mode", "allow")
            allowlist = {str(x).lower() for x in (domains.get("allowlist") or [])}
            denylist = {str(x).lower() for x in (domains.get("denylist") or [])}
            host = self._extract_host(url)
            if not host:
                return (True, "")
            candidates = self._host_candidates(host)
            if candidates & denylist:
                return (False, f"domain denied by policy: {host}")
            if mode == "deny":
                if candidates & allowlist:
                    return (True, "")
                return (False, f"domain denied by policy: {host}")
            return (True, "")

    def is_observe(self):
        with self._lock:
            return str(self._policy.get("mode", "normal")) == "observe"

    def write_allowed(self, path):
        """Enforce the per-path write allowlist.

        Empty ``write_roots`` => unrestricted (backward compatible). Otherwise
        the resolved target must be equal to, or inside, one of the listed roots.
        Returns ``(allowed: bool, reason: str)``.
        """
        with self._lock:
            roots = list(self._policy.get("write_roots") or [])
        if not roots:
            return True, ""
        if not path:
            return False, "empty path"
        try:
            resolved = os.path.normcase(os.path.realpath(str(path)))
        except Exception as e:
            return False, f"invalid path: {e}"
        for root in roots:
            try:
                root_n = os.path.normcase(os.path.realpath(str(root)))
                if resolved == root_n or os.path.commonpath([resolved, root_n]) == root_n:
                    return True, ""
            except (ValueError, OSError):
                continue
        return False, f"path outside write allowlist ({len(roots)} root(s))"

    @staticmethod
    def _extract_host(url):
        try:
            s = str(url).strip()
            if not s:
                return ""
            parsed = urlparse(s)
            netloc = parsed.netloc or ""
            if not netloc:
                # Bare host or path-only string — take the first segment.
                netloc = s.split("/", 1)[0]
                # Drop any query/fragment so they can't be folded into the host
                # and defeat denylist matching (e.g. "evil.com?x=1").
                netloc = netloc.split("?", 1)[0].split("#", 1)[0]
            if "@" in netloc:
                netloc = netloc.rsplit("@", 1)[1]
            if netloc.startswith("[") and "]" in netloc:
                host = netloc[1:].split("]", 1)[0]
            else:
                host = netloc.split(":", 1)[0]
            return host.lower().strip()
        except (ValueError, AttributeError, TypeError):
            try:
                return str(url).lower().strip()
            except Exception:
                return ""

    @staticmethod
    def _host_candidates(host):
        """Return {host} plus every parent domain suffix for hierarchical matching."""
        out = {host}
        parts = host.split(".")
        for i in range(1, len(parts)):
            out.add(".".join(parts[i:]))
        return out

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------
    def _roll_hour(self):
        # Caller must hold self._lock.
        cur = _now_hour_bucket()
        if cur != self._hour_bucket:
            self._hour_bucket = cur
            self._hour_counts = {a: 0 for a in _BUDGET_ACTIONS}

    def check_budget(self, action):
        with self._lock:
            if not self._policy.get("enabled"):
                return (True, "")
            budgets = self._policy.get("budgets") or {}
            if not budgets.get("enabled"):
                return (True, "")
            if action not in _BUDGET_ACTIONS:
                return (True, "")
            self._roll_hour()
            per_hour = budgets.get("per_hour") or {}
            per_goal = budgets.get("per_goal") or {}
            cap_h = per_hour.get(action)
            cap_g = per_goal.get(action)
            used_h = self._hour_counts.get(action, 0)
            used_g = self._goal_counts.get(action, 0)
            if isinstance(cap_h, (int, float)) and not isinstance(cap_h, bool):
                if used_h + 1 > cap_h:
                    return (False, f"budget exceeded for {action}")
            if isinstance(cap_g, (int, float)) and not isinstance(cap_g, bool):
                if used_g + 1 > cap_g:
                    return (False, f"budget exceeded for {action}")
            self._hour_counts[action] = used_h + 1
            self._goal_counts[action] = used_g + 1
            return (True, "")

    def budget_remaining(self, action):
        with self._lock:
            self._roll_hour()
            budgets = self._policy.get("budgets") or {}
            per_hour = budgets.get("per_hour") or {}
            per_goal = budgets.get("per_goal") or {}
            cap_h = per_hour.get(action, 0) or 0
            cap_g = per_goal.get(action, 0) or 0
            used_h = self._hour_counts.get(action, 0)
            used_g = self._goal_counts.get(action, 0)
            try:
                cap_h_num = float(cap_h)
            except (TypeError, ValueError):
                cap_h_num = 0
            try:
                cap_g_num = float(cap_g)
            except (TypeError, ValueError):
                cap_g_num = 0
            return {
                "per_hour": {
                    "cap": cap_h,
                    "used": used_h,
                    "remaining": max(0, int(cap_h_num - used_h)),
                },
                "per_goal": {
                    "cap": cap_g,
                    "used": used_g,
                    "remaining": max(0, int(cap_g_num - used_g)),
                },
            }

    def budget_usage(self):
        with self._lock:
            return {a: self.budget_remaining(a) for a in _BUDGET_ACTIONS}

    def reset_budgets(self):
        with self._lock:
            self._hour_bucket = _now_hour_bucket()
            self._hour_counts = {a: 0 for a in _BUDGET_ACTIONS}
            self._goal_counts = {a: 0 for a in _BUDGET_ACTIONS}

    def begin_goal(self, goal_id):
        with self._lock:
            self._goal_id = str(goal_id) if goal_id is not None else None
            self._goal_counts = {a: 0 for a in _BUDGET_ACTIONS}

    def current_goal(self):
        with self._lock:
            return self._goal_id

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def record_block(self, action, target, reason):
        try:
            entry = {
                "timestamp": _iso_now(),
                "action": str(action) if action is not None else "",
                "target": str(target) if target is not None else "",
                "reason": str(reason) if reason is not None else "",
                "allowed": False,
            }
        except Exception as e:
            _log(f"[governance] record_block failed to build entry: {e}")
            return
        with self._lock:
            self._audit.append(entry)
            try:
                line = json.dumps(entry, ensure_ascii=False)
                with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except (OSError, TypeError, ValueError) as e:
                _log(f"[governance] audit write failed: {e}")

    def audit(self, limit=200):
        with self._lock:
            try:
                lim = int(limit)
            except (TypeError, ValueError):
                lim = 200
            if lim <= 0:
                lim = 200
            if lim > _AUDIT_MAX_MEM:
                lim = _AUDIT_MAX_MEM
            entries = list(self._audit)
            return list(reversed(entries[-lim:]))

    def audit_count(self):
        with self._lock:
            return len(self._audit)

    # ------------------------------------------------------------------
    # Redaction
    # ------------------------------------------------------------------
    def redact(self, text):
        try:
            if not text:
                return text
            if not isinstance(text, str):
                return text
            with self._lock:
                redact_cfg = self._policy.get("redact") or {}
                enabled = bool(redact_cfg.get("enabled", True))
            if not enabled:
                return text
            if len(text) > _REDACT_MAX_CHARS:
                _log(f"[governance] redact input too large ({len(text)} chars), returning placeholder")
                return "[REDACTED - input too large]"
            out = text
            for pattern, repl in _REDACT_PATTERNS:
                try:
                    out = pattern.sub(repl, out)
                except (re.error, TypeError, ValueError):
                    continue
            return out
        except Exception as e:
            _log(f"[governance] redact error: {e}")
            return text


_GOVERNOR = _Governor()


def enable_observe():
    """Enable observe mode (used by the --observe CLI flag)."""
    policy, errors = _GOVERNOR.update_policy({"mode": "observe"})
    _log(f"[governance] observe mode enabled (errors={errors})")
    return policy


def check_write_path(path):
    """Enforce the per-path write allowlist. Returns (allowed, reason)."""
    return _GOVERNOR.write_allowed(path)


def get_governor():
    """Return the module-level governor singleton."""
    return _GOVERNOR


def register_routes(app, state, require_auth):
    """Register /governance/* HTTP endpoints and expose helpers on state."""

    @app.before_request
    def _observe_guard():
        if not _GOVERNOR.is_observe():
            return None
        path = (request.path or "").rstrip("/") or "/"
        for prefix in _OBSERVE_BLOCKED_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                _log(f"[governance] observe mode blocked {request.method} {path}")
                return jsonify({
                    "ok": False,
                    "error": "observe mode: mutating endpoint blocked",
                    "path": request.path,
                }), 403
        return None

    @app.route("/governance/policy", methods=["GET"])
    @require_auth
    def route_governance_policy_get():
        return jsonify({"ok": True, "policy": _GOVERNOR.get_policy()})

    @app.route("/governance/policy", methods=["POST"])
    @require_auth
    def route_governance_policy_post():
        try:
            partial = request.get_json(silent=True)
        except Exception:
            partial = None
        if partial is None:
            partial = {}
        if not isinstance(partial, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400
        new_policy, errors = _GOVERNOR.update_policy(partial)
        if errors:
            return jsonify({"ok": False, "policy": new_policy, "errors": errors}), 400
        return jsonify({"ok": True, "policy": new_policy, "errors": errors})

    @app.route("/governance/policy/reset", methods=["POST"])
    @require_auth
    def route_governance_policy_reset():
        new_policy = _GOVERNOR.reset_policy()
        return jsonify({"ok": True, "policy": new_policy})

    @app.route("/governance/audit", methods=["GET"])
    @require_auth
    def route_governance_audit():
        try:
            limit = int(request.args.get("limit", 200))
        except (TypeError, ValueError):
            limit = 200
        entries = _GOVERNOR.audit(limit=limit)
        return jsonify({"ok": True, "count": len(entries), "entries": entries})

    @app.route("/governance/status", methods=["GET"])
    @require_auth
    def route_governance_status():
        policy = _GOVERNOR.get_policy()
        apps_cfg = policy.get("apps") or {}
        domains_cfg = policy.get("domains") or {}
        budgets_cfg = policy.get("budgets") or {}
        return jsonify({
            "ok": True,
            "enabled": bool(policy.get("enabled")),
            "observe": _GOVERNOR.is_observe(),
            "write_roots": policy.get("write_roots") or [],
            "mode": {
                "apps": apps_cfg.get("mode", "allow"),
                "domains": domains_cfg.get("mode", "allow"),
            },
            "budgets_enabled": bool(budgets_cfg.get("enabled")),
            "budgets": _GOVERNOR.budget_usage(),
            "goal_id": _GOVERNOR.current_goal(),
            "audit_count": _GOVERNOR.audit_count(),
        })

    @app.route("/governance/budget/reset", methods=["POST"])
    @require_auth
    def route_governance_budget_reset():
        _GOVERNOR.reset_budgets()
        return jsonify({"ok": True})

    @app.route("/governance/goal/begin", methods=["POST"])
    @require_auth
    def route_governance_goal_begin():
        try:
            body = request.get_json(silent=True)
        except Exception:
            body = None
        if body is None:
            body = {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400
        goal_id = body.get("goal_id")
        if goal_id is None or str(goal_id).strip() == "":
            return jsonify({"ok": False, "error": "goal_id required"}), 400
        goal_id = str(goal_id)
        _GOVERNOR.begin_goal(goal_id)
        return jsonify({"ok": True, "goal_id": goal_id})

    @app.route("/governance/redact", methods=["POST"])
    @require_auth
    def route_governance_redact():
        try:
            body = request.get_json(silent=True)
        except Exception:
            body = None
        if body is None:
            body = {}
        text = ""
        if isinstance(body, dict):
            text = body.get("text", "")
            if text is None:
                text = ""
        if not isinstance(text, str):
            try:
                text = str(text)
            except Exception:
                text = ""
        redacted = _GOVERNOR.redact(text)
        return jsonify({
            "ok": True,
            "redacted": redacted,
            "changed": redacted != text,
        })

    state.governance = {
        "check_app": _GOVERNOR.check_app,
        "check_url": _GOVERNOR.check_url,
        "check_budget": _GOVERNOR.check_budget,
        "redact": _GOVERNOR.redact,
        "record_block": _GOVERNOR.record_block,
        "get_policy": _GOVERNOR.get_policy,
        "budget_usage": _GOVERNOR.budget_usage,
    }
