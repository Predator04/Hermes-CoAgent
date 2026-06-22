"""
Telegram relay routes for CoAgent.
Sends Codex audit findings to Telegram via Bot API.

Endpoints:
  POST /telegram/configure     - Save bot_token + chat_id (requires both)
  POST /telegram/register-chat - Register this chat as target for findings
  GET  /telegram/config        - View config (token masked)
  POST /telegram/clear         - Clear config
  POST /agent/exec-and-send    - Run Codex, extract findings, send to Telegram
  GET  /telegram/status        - Check config + last send status
"""

import json, os, time, urllib.request
from pathlib import Path
from flask import Blueprint, jsonify, request

from shared import COAGENT_DIR, _console, _log, _json_body

telegram_bp = Blueprint("telegram_relay", __name__)
CONFIG_FILE = COAGENT_DIR / "telegram_config.json"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
FINDING_PREFIXES = ("## FINDING:", "Severity:", "Issue:", "Fix:", "---")


def _load_config():
    """Load saved Telegram config. Returns dict with keys or None."""
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _console(f"[telegram] config load failed: {exc}")
    return None


def _save_config(data):
    """Save config, write atomically."""
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)
    _console("[telegram] config saved")


def _resolve_target_chat(config):
    """Resolve the best chat_id to use. Prefers target_chat_id over chat_id."""
    return config.get("target_chat_id") or config.get("chat_id")


def _mask_token(token):
    """Show first 4 + last 4 chars of token."""
    if not token or len(token) < 10:
        return "***"
    return token[:4] + "..." + token[-4:]


def _send_telegram(bot_token, chat_id, text, parse_mode="Markdown"):
    """Send a message via Telegram Bot API. Returns (ok, response_or_error)."""
    if not text or not text.strip():
        return True, "nothing to send"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text[:4096],  # Telegram limit
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode()
    url = TELEGRAM_API.format(token=bot_token)
    try:
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("ok"):
            return True, result
        return False, result.get("description", "unknown error")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _extract_findings(text):
    """Extract FINDING sections from Codex stdout."""
    lines = text.split("\n")
    findings = []
    current = []
    in_finding = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## FINDING:"):
            if current:
                findings.append("\n".join(current))
            current = [stripped]
            in_finding = True
        elif in_finding:
            if stripped == "---":
                if current:
                    findings.append("\n".join(current))
                current = []
                in_finding = False
            elif any(stripped.startswith(p) for p in FINDING_PREFIXES):
                current.append(stripped)
            elif current and len(current) < 15:
                current.append(stripped)

    if current:
        findings.append("\n".join(current))

    return findings


@telegram_bp.route("/telegram/configure", methods=["POST"])
def route_telegram_configure():
    data = _json_body()
    bot_token = (data.get("bot_token") or "").strip()
    chat_id = (data.get("chat_id") or data.get("target_chat_id") or "").strip()

    if not bot_token or not chat_id:
        return jsonify({"error": "bot_token and chat_id are required"}), 400

    # Verify by sending a test message
    test_ok, test_msg = _send_telegram(bot_token, chat_id,
        "✅ *CoAgent Telegram Relay configured!*\n\n"
        "Codex audit findings will be sent here.", parse_mode="Markdown")

    config = {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "target_chat_id": chat_id,
        "last_send": None,
        "last_error": None if test_ok else str(test_msg),
        "configured_at": time.time(),
    }
    _save_config(config)

    if test_ok:
        return jsonify({"status": "configured", "test_message": "sent", "chat_id": chat_id})
    return jsonify({
        "status": "configured_but_test_failed",
        "error": str(test_msg),
        "chat_id": chat_id,
    }), 200


@telegram_bp.route("/telegram/register-chat", methods=["POST"])
def route_telegram_register_chat():
    """Register this chat as the target for Codex findings."""
    data = _json_body()
    chat_id = (data.get("chat_id") or "").strip()
    if not chat_id:
        return jsonify({"error": "chat_id is required"}), 400

    config = _load_config()
    if not config or not config.get("bot_token"):
        return jsonify({"error": "Telegram not configured. Configure bot_token first via /telegram/configure"}), 400

    # Test with current bot token
    test_ok, test_msg = _send_telegram(config["bot_token"], chat_id,
        "✅ *This chat is now the target for CoAgent relay!*\n\n"
        "Audit findings and Codex output will be delivered here.", parse_mode="Markdown")

    if test_ok:
        config["target_chat_id"] = chat_id
        config["chat_id"] = chat_id
        config["last_error"] = None
        _save_config(config)
        return jsonify({"status": "registered", "chat_id": chat_id})

    return jsonify({"error": f"Failed to reach chat {chat_id}: {test_msg}"}), 400


@telegram_bp.route("/telegram/config", methods=["GET"])
def route_telegram_config():
    config = _load_config()
    if not config:
        return jsonify({"configured": False})
    return jsonify({
        "configured": True,
        "bot_token": _mask_token(config.get("bot_token")),
        "chat_id": config.get("chat_id"),
        "target_chat_id": config.get("target_chat_id"),
        "last_send": config.get("last_send"),
        "last_error": config.get("last_error"),
        "configured_at": config.get("configured_at"),
    })


@telegram_bp.route("/telegram/clear", methods=["POST"])
def route_telegram_clear():
    try:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        return jsonify({"status": "cleared"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@telegram_bp.route("/agent/exec-and-send", methods=["POST"])
def route_agent_exec_and_send():
    """Run Codex, extract findings, send to Telegram."""
    config = _load_config()
    if not config or not config.get("bot_token") or not config.get("chat_id"):
        return jsonify({"error": "Telegram not configured. POST /telegram/configure first"}), 400

    data = _json_body()
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    timeout = data.get("timeout", 600)

    # Run agent (sync blocking call)
    try:
        from routes_agent import _execute_agent
    except ImportError:
        return jsonify({"error": "routes_agent not available"}), 500

    try:
        result = _execute_agent(
            prompt=prompt,
            agent_name=data.get("agent"),
            model=data.get("model"),
            timeout=timeout,
            workdir=data.get("workdir"),
            purpose="exec",
            read_only=False,
        )
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        _console(f"[telegram] exec failed: {error_msg}")
        config["last_error"] = error_msg
        config["last_send"] = time.time()
        _save_config(config)
        return jsonify({"error": error_msg}), 500

    # Extract findings from stdout
    stdout = result.get("stdout", "")
    all_text = result.get("stdout", "") + "\n" + result.get("stderr", "")
    findings = _extract_findings(all_text)

    if not findings:
        # No structured findings — send raw stdout summary
        msg = f"🤖 *Codex Complete* (exit: {result.get('exit_code')})\n\n"
        if stdout:
            msg += "```\n" + stdout[:3500] + "\n```"
        else:
            msg += "No stdout output."
        msg += f"\n\n_Duration: {result.get('duration_seconds', '?')}s_"
        target_chat = _resolve_target_chat(config)
        ok, resp_data = _send_telegram(config["bot_token"], target_chat, msg)
        all_errors = []
        sent_count = 1
    else:
        # Send each finding as a separate message
        sent_count = 0
        errors = []
        target_chat = _resolve_target_chat(config)
        for i, finding in enumerate(findings):
            msg = finding[:4096]
            ok, resp_data = _send_telegram(config["bot_token"], target_chat, msg)
            if ok:
                sent_count += 1
            else:
                errors.append(str(resp_data))
            time.sleep(0.3)  # Rate limit

        summary = f"🤖 *Codex Audit Complete*\n"
        summary += f"📊 {len(findings)} findings found, {sent_count} sent\n"
        summary += f"⏱ {result.get('duration_seconds', '?')}s  |  Exit: {result.get('exit_code')}"
        if errors:
            summary += f"\n❌ {len(errors)} send errors"
        ok, resp_data = _send_telegram(config["bot_token"], target_chat, summary)
        all_errors = errors

    # Update config with last send info
    config["last_send"] = time.time()
    config["last_error"] = str(all_errors[-1]) if all_errors else None
    _save_config(config)

    return jsonify({
        "status": "sent" if ok else "send_failed",
        "findings_count": len(findings),
        "sent_count": sent_count if findings else 1,
        "exit_code": result.get("exit_code"),
        "duration_seconds": result.get("duration_seconds"),
        "errors": all_errors if all_errors else None,
    })


@telegram_bp.route("/telegram/status", methods=["GET"])
def route_telegram_status():
    config = _load_config()
    if not config:
        return jsonify({"configured": False, "status": "not_configured"})
    return jsonify({
        "configured": True,
        "has_token": bool(config.get("bot_token")),
        "chat_id": config.get("chat_id"),
        "target_chat_id": config.get("target_chat_id"),
        "last_send": config.get("last_send"),
        "last_error": config.get("last_error"),
        "configured_at": config.get("configured_at"),
        "status": "ok" if not config.get("last_error") else "last_send_failed",
    })


def register_routes(app, state, require_auth):
    """Register all telegram relay routes."""
    from routes_agent import _auth_blueprint
    _auth_blueprint(telegram_bp, require_auth)
    app.register_blueprint(telegram_bp)
    state.telegram_relay = {
        "configured": CONFIG_FILE.exists(),
        "config_file": str(CONFIG_FILE),
    }
    _console("[telegram] routes registered")
