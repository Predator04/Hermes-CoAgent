"""Agent self-verification loop.

After the agent performs an action, this route grabs a fresh screenshot,
runs it through the existing vision provider (reusing helpers from
routes_screen_vision and routes_vision), compares what is on screen against
an expected description supplied by the caller, and reports pass/fail.

When configured, a failed verification auto-retries the "last action" the
caller registered (POST /verify/last-action) or that was supplied inline on
the check request, then re-verifies.

Endpoints:
  POST /verify/check         - screenshot + describe + compare, optional retry
  POST /verify/last-action   - remember the most recent action for later retry
  GET  /verify/last-action   - inspect the currently-remembered action
  POST /verify/clear         - forget the remembered action / counters
  GET  /verify/status        - counters + last verdict

All third-party / Windows-only imports are wrapped in try/except so the file
imports cleanly under a Linux syntax check.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request

from flask import jsonify

from shared import _json_body, _log, _self_port


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_STATE = {
    "total_checks": 0,
    "total_pass": 0,
    "total_fail": 0,
    "total_retries": 0,
    "last_verdict": None,
    "last_reason": None,
    "last_expected": None,
    "last_ts": 0,
}
_LAST_ACTION = {"path": None, "payload": None, "method": "POST", "ts": 0}

_STOP_WORDS = {
    "a", "an", "and", "at", "be", "by", "for", "in", "is", "it", "of", "on",
    "or", "should", "shows", "that", "the", "then", "there", "this", "to",
    "was", "will", "with",
}


# ---------------------------------------------------------------------------
# Helpers that call back into CoAgent's own HTTP surface
# (matches the pattern used by routes_finder / routes_screen_vision)
# ---------------------------------------------------------------------------

def _auth_token():
    try:
        import auth
        return getattr(auth, "AUTH_TOKEN", "") or ""
    except Exception:
        return ""


def _coagent_request(path, payload=None, method="POST", timeout=20):
    """POST/GET to our own Flask server. Returns parsed JSON or {'error': ...}."""
    url = f"http://127.0.0.1:{_self_port()}{path}"
    headers = {"Accept": "application/json"}
    token = _auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None and method.upper() != "GET":
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {"raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            data = {"error": str(exc)}
        if not isinstance(data, dict):
            data = {"error": f"HTTP {exc.code}: unexpected body type", "body": data}
        data.setdefault("status_code", exc.code)
        return data
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Screenshot capture (region-aware, reuses routes_vision._grab_region)
# ---------------------------------------------------------------------------

def _capture(region=None, window=None):
    """Return (PIL.Image, (offx, offy)) for the requested region.

    Falls back cleanly if PIL / mss are absent (Linux CI).
    """
    try:
        from routes_vision import _grab_region
    except Exception as exc:
        return None, (0, 0), f"routes_vision unavailable: {exc}"
    try:
        img, offset = _grab_region(region=region, window=window)
        if img is None:
            return None, (0, 0), "screen capture failed"
        return img, offset, None
    except Exception as exc:
        return None, (0, 0), f"capture error: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Description via the existing vision provider
# ---------------------------------------------------------------------------

def _describe_image(pil_img):
    """Return (text, words, method) using existing OCR helpers.

    Prefers routes_vision._ocr_image (Windows.Media.Ocr with words+bboxes),
    falls back to routes_screen_vision._describe_via_ocr (text summary).
    """
    text = ""
    words = []
    method = "none"
    try:
        from routes_vision import _ocr_image
        result = _ocr_image(pil_img) or {}
        if result.get("success"):
            text = result.get("text", "") or ""
            words = result.get("words", []) or []
            method = "routes_vision._ocr_image"
            return text, words, method
    except Exception as exc:
        _log(f"[verify] routes_vision._ocr_image failed: {exc}")

    # Fallback: routes_screen_vision (expects raw bytes)
    try:
        import io
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        raw = buf.getvalue()
        from routes_screen_vision import _describe_via_ocr
        result = _describe_via_ocr(raw) or {}
        if result.get("success"):
            text = result.get("text_snippet", "") or ""
            method = "routes_screen_vision._describe_via_ocr"
    except Exception as exc:
        _log(f"[verify] routes_screen_vision fallback failed: {exc}")
    return text, words, method


# ---------------------------------------------------------------------------
# Comparison: expected description vs. observed OCR text
# ---------------------------------------------------------------------------

def _keywords_from_expected(expected):
    """Tokenize the expected description into keyword candidates."""
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_'\-]*", str(expected or ""))
    keywords = []
    seen = set()
    for tok in tokens:
        low = tok.lower()
        if low in _STOP_WORDS or len(low) < 2:
            continue
        if low in seen:
            continue
        seen.add(low)
        keywords.append(tok)
    return keywords


def _score(expected, text, keywords_override=None, mode="any"):
    """Return dict with pass/fail metrics."""
    normalized_text = (text or "").lower()
    expected_norm = str(expected or "").strip().lower()

    substring_hit = bool(expected_norm) and expected_norm in normalized_text
    keywords = keywords_override if keywords_override else _keywords_from_expected(expected)
    matched = [kw for kw in keywords if kw.lower() in normalized_text]
    missing = [kw for kw in keywords if kw.lower() not in normalized_text]

    if keywords:
        ratio = len(matched) / float(len(keywords))
    else:
        ratio = 1.0 if substring_hit else 0.0

    if mode == "all":
        passed = bool(keywords) and not missing
    elif mode == "substring":
        passed = substring_hit
    else:  # "any" (default) - ratio-based
        passed = substring_hit or (bool(keywords) and ratio >= 0.5)

    return {
        "passed": passed,
        "score": round(ratio, 3),
        "substring_match": substring_hit,
        "matched_keywords": matched,
        "missing_keywords": missing,
        "keyword_count": len(keywords),
    }


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------

def _resolve_retry_action(request_body):
    """Return the action dict to retry, or None.

    Priority:
      1. request_body['retry']['action'] (inline)
      2. request_body['action']          (top-level convenience)
      3. remembered _LAST_ACTION (if request_body says use_last_action or
         retry.use_last_action is True; also used as a fallback when retry
         is enabled but no inline action is supplied)
    """
    retry_cfg = request_body.get("retry") if isinstance(request_body.get("retry"), dict) else {}
    inline = retry_cfg.get("action") or request_body.get("action")
    if isinstance(inline, dict) and inline.get("path"):
        return inline

    prefer_last = (
        bool(request_body.get("use_last_action"))
        or bool(retry_cfg.get("use_last_action"))
        or bool(retry_cfg)  # retry block present but no inline action -> try last
    )
    if prefer_last:
        with _LOCK:
            last = dict(_LAST_ACTION)
        if last.get("path"):
            return last
    return None


def _run_action(action):
    """Invoke the stored action via the CoAgent HTTP surface."""
    path = action.get("path")
    if not path or not str(path).startswith("/"):
        return {"error": "invalid action path"}
    method = (action.get("method") or "POST").upper()
    payload = action.get("payload") if isinstance(action.get("payload"), (dict, list)) else None
    return _coagent_request(path, payload=payload, method=method,
                            timeout=_clamp(action.get("timeout", 20), 1, 120, 20))


def _clamp(value, lo, hi, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    @app.route("/verify/check", methods=["POST"])
    @require_auth
    def route_verify_check():
        """Screenshot-after-action verification.

        Body:
          expected        (str, required) - description of what should be on
                                            screen; used for keyword scoring
          keywords        (list[str])     - explicit keyword override
          region          ({x,y,w,h})     - restrict capture area
          window          (str)           - restrict capture to a window title
          mode            "any"|"all"|"substring" (default "any")
          retry: {
              enabled        (bool, default True when retry block present)
              max_attempts   (int 1..5, default 1)
              delay_ms       (int 0..10000, default 400)
              action         ({path, method, payload, timeout}, optional)
              use_last_action(bool, default True when no inline action)
          }
          action / use_last_action        - top-level shortcuts

        Returns pass/fail plus per-attempt verdicts and the retry results.
        """
        body = _json_body() or {}
        expected = body.get("expected")
        if not isinstance(expected, str) or not expected.strip():
            return jsonify({"error": "Missing required field: expected"}), 400

        region = body.get("region") if isinstance(body.get("region"), dict) else None
        window = (body.get("window") or "").strip() or None
        mode = (body.get("mode") or "any").strip().lower()
        if mode not in ("any", "all", "substring"):
            mode = "any"
        keywords_override = body.get("keywords") if isinstance(body.get("keywords"), list) else None
        if keywords_override:
            keywords_override = [str(k) for k in keywords_override if str(k).strip()]

        retry_cfg = body.get("retry") if isinstance(body.get("retry"), dict) else {}
        retry_enabled = bool(retry_cfg) or bool(body.get("action")) or bool(body.get("use_last_action"))
        if "enabled" in retry_cfg:
            retry_enabled = bool(retry_cfg.get("enabled"))
        max_attempts = _clamp(retry_cfg.get("max_attempts", 1), 1, 5, 1)
        delay_ms = _clamp(retry_cfg.get("delay_ms", 400), 0, 10000, 400)

        attempts = []
        retry_action = None
        final_verdict = None
        final_text = ""
        final_method = "none"

        # First verify + up-to-max_attempts retry cycles
        for attempt_index in range(max_attempts + 1):
            t0 = time.time()
            img, _offset, cap_err = _capture(region=region, window=window)
            if img is None:
                attempt = {
                    "attempt": attempt_index,
                    "captured": False,
                    "error": cap_err or "capture failed",
                    "elapsed_ms": round((time.time() - t0) * 1000, 1),
                }
                attempts.append(attempt)
                break

            text, _words, method = _describe_image(img)
            verdict = _score(expected, text, keywords_override=keywords_override, mode=mode)
            attempts.append({
                "attempt": attempt_index,
                "captured": True,
                "method": method,
                "text_len": len(text or ""),
                "text_snippet": (text or "")[:400],
                **verdict,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })
            final_verdict = verdict
            final_text = text or ""
            final_method = method

            if verdict["passed"] or not retry_enabled or attempt_index >= max_attempts:
                break

            if retry_action is None:
                retry_action = _resolve_retry_action(body)
                if not retry_action:
                    attempts[-1]["retry_skipped"] = "no action to retry"
                    break

            with _LOCK:
                _STATE["total_retries"] += 1
            retry_result = _run_action(retry_action)
            attempts[-1]["retry"] = {
                "path": retry_action.get("path"),
                "method": (retry_action.get("method") or "POST").upper(),
                "result": retry_result,
            }
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

        passed = bool(final_verdict and final_verdict["passed"])
        reason = None
        if not passed and final_verdict:
            reason = ("missing: " + ", ".join(final_verdict.get("missing_keywords", [])[:8])
                      if final_verdict.get("missing_keywords") else "no expected text found")
        elif not final_verdict:
            reason = "capture failed"

        with _LOCK:
            _STATE["total_checks"] += 1
            if passed:
                _STATE["total_pass"] += 1
            else:
                _STATE["total_fail"] += 1
            _STATE["last_verdict"] = "pass" if passed else "fail"
            _STATE["last_reason"] = reason
            _STATE["last_expected"] = str(expected)[:200]
            _STATE["last_ts"] = int(time.time())

        return jsonify({
            "ok": True,
            "passed": passed,
            "expected": expected,
            "mode": mode,
            "score": final_verdict["score"] if final_verdict else 0.0,
            "matched_keywords": final_verdict.get("matched_keywords", []) if final_verdict else [],
            "missing_keywords": final_verdict.get("missing_keywords", []) if final_verdict else [],
            "text_snippet": final_text[:400],
            "method": final_method,
            "attempts": attempts,
            "retry_used": any("retry" in a for a in attempts),
            "reason": reason,
        })

    @app.route("/verify/last-action", methods=["POST"])
    @require_auth
    def route_verify_set_last_action():
        """Remember an action so a later /verify/check can auto-retry it.

        Body: {path (required), method="POST", payload={...}, timeout=20}
        """
        body = _json_body() or {}
        path = body.get("path")
        if not path or not isinstance(path, str) or not path.startswith("/"):
            return jsonify({"error": "path is required and must start with '/'"}), 400
        with _LOCK:
            _LAST_ACTION["path"] = path
            _LAST_ACTION["method"] = (body.get("method") or "POST").upper()
            _LAST_ACTION["payload"] = body.get("payload") if isinstance(body.get("payload"), (dict, list)) else None
            _LAST_ACTION["timeout"] = _clamp(body.get("timeout", 20), 1, 120, 20)
            _LAST_ACTION["ts"] = int(time.time())
            snapshot = dict(_LAST_ACTION)
        return jsonify({"ok": True, "last_action": snapshot})

    @app.route("/verify/last-action", methods=["GET"])
    @require_auth
    def route_verify_get_last_action():
        with _LOCK:
            snapshot = dict(_LAST_ACTION)
        return jsonify({"ok": True, "last_action": snapshot})

    @app.route("/verify/clear", methods=["POST"])
    @require_auth
    def route_verify_clear():
        with _LOCK:
            _LAST_ACTION.update({"path": None, "payload": None, "method": "POST", "timeout": 20, "ts": 0})
            _STATE.update({
                "total_checks": 0,
                "total_pass": 0,
                "total_fail": 0,
                "total_retries": 0,
                "last_verdict": None,
                "last_reason": None,
                "last_expected": None,
                "last_ts": 0,
            })
        return jsonify({"ok": True})

    @app.route("/verify/status", methods=["GET"])
    @require_auth
    def route_verify_status():
        with _LOCK:
            return jsonify({"ok": True, "state": dict(_STATE), "last_action": dict(_LAST_ACTION)})
