"""Timed reminder and push alert routes."""

import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from shared import COAGENT_DIR, _console, _json_body


reminders_bp = Blueprint("reminders", __name__)

DB_FILE = COAGENT_DIR / "reminders.db"
CHECK_INTERVAL_SECONDS = 30

_DB_LOCK = threading.RLock()
_SCHEDULER_THREAD = None
_SCHEDULER_LOCK = threading.Lock()


def _now():
    return datetime.now().replace(microsecond=0)


def _db():
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _DB_LOCK, _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                trigger_at TEXT NOT NULL,
                repeat_interval TEXT NOT NULL DEFAULT 'none',
                delivered_to TEXT NOT NULL DEFAULT 'telegram',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_delivered_at TEXT,
                last_error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, trigger_at)")
        conn.commit()


def _row_to_dict(row):
    return {key: row[key] for key in row.keys()}


def _parse_time_token(token):
    token = str(token or "").strip().lower()
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", token)
    if not match:
        raise ValueError("time must look like 9am, 09:00, or 21:30")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = match.group(3)
    if suffix == "pm" and hour != 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError("time is out of range")
    return hour, minute


def _parse_trigger_at(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("trigger_at is required")
    lowered = raw.lower()
    now = _now()
    match = re.fullmatch(r"in\s+(\d+)\s*([smhd])", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "s":
            return now + timedelta(seconds=amount)
        if unit == "m":
            return now + timedelta(minutes=amount)
        if unit == "h":
            return now + timedelta(hours=amount)
        return now + timedelta(days=amount)
    match = re.fullmatch(r"tomorrow\s+(.+)", lowered)
    if match:
        hour, minute = _parse_time_token(match.group(1))
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
    try:
        cleaned = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed.replace(microsecond=0)
    except ValueError as exc:
        raise ValueError("trigger_at must be ISO format, 'in 5m', 'in 2h', or 'tomorrow 9am'") from exc


def _normalize_repeat(value):
    repeat = str(value or "none").strip().lower()
    aliases = {"": "none", "no": "none", "false": "none", "0": "none"}
    repeat = aliases.get(repeat, repeat)
    if repeat not in {"none", "hourly", "daily", "weekly"}:
        raise ValueError("repeat must be one of none, hourly, daily, weekly")
    return repeat


def _normalize_delivery(data):
    deliver_to = str(data.get("deliver_to") or data.get("delivered_to") or "telegram").strip()
    if deliver_to == "webhook" and data.get("webhook_url"):
        deliver_to = f"webhook:{str(data.get('webhook_url')).strip()}"
    if deliver_to not in {"telegram", "toast"} and not (
        deliver_to.startswith("telegram:") or deliver_to.startswith("webhook:")
    ):
        if deliver_to == "webhook":
            env_url = os.environ.get("COAGENT_REMINDER_WEBHOOK_URL", "").strip()
            if env_url:
                return f"webhook:{env_url}"
        raise ValueError("deliver_to must be telegram, telegram:<chat_id>, toast, webhook:<url>, or webhook_url")
    return deliver_to


def _next_trigger(trigger_at, repeat):
    if repeat == "hourly":
        return trigger_at + timedelta(hours=1)
    if repeat == "daily":
        return trigger_at + timedelta(days=1)
    if repeat == "weekly":
        return trigger_at + timedelta(days=7)
    return None


def _load_reminder(reminder_id):
    with _DB_LOCK, _db() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (int(reminder_id),)).fetchone()
    return _row_to_dict(row) if row else None


def _send_telegram(delivered_to, title, message):
    try:
        from routes_telegram import _load_config, _resolve_target_chat, _send_telegram_message
    except Exception as exc:
        return False, f"telegram helper unavailable: {exc}"
    config = _load_config()
    if not config:
        return False, "telegram not configured"
    bot_token = config.get("bot_token")
    chat_id = delivered_to.split(":", 1)[1] if delivered_to.startswith("telegram:") else _resolve_target_chat(config)
    if not bot_token or not chat_id:
        return False, "telegram bot_token or chat_id missing"
    text = f"{title}\n\n{message}" if title else message
    return _send_telegram_message(bot_token, chat_id, text)


def _send_toast(title, message):
    try:
        from routes_toast import HAS_WIN11TOAST, _win11_toast
    except Exception as exc:
        return False, f"toast helper unavailable: {exc}"
    if not HAS_WIN11TOAST or _win11_toast is None:
        return False, "win11toast not installed"
    try:
        _win11_toast(title, message)
        return True, {"status": "shown"}
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _send_webhook(delivered_to, title, message, reminder):
    url = delivered_to.split(":", 1)[1] if ":" in delivered_to else ""
    if not url:
        return False, "webhook URL missing"
    payload = json.dumps({
        "id": reminder.get("id"),
        "title": title,
        "message": message,
        "trigger_at": reminder.get("trigger_at"),
        "repeat": reminder.get("repeat_interval"),
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
        return True, {"status_code": getattr(response, "status", 200), "body": body}
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _deliver(reminder):
    delivered_to = reminder.get("delivered_to") or "telegram"
    title = reminder.get("title") or "Reminder"
    message = reminder.get("message") or ""
    if delivered_to.startswith("telegram"):
        return _send_telegram(delivered_to, title, message)
    if delivered_to == "toast":
        return _send_toast(title, message)
    if delivered_to.startswith("webhook"):
        return _send_webhook(delivered_to, title, message, reminder)
    return False, f"unsupported delivery target: {delivered_to}"


def _mark_delivery(reminder, ok, response, manual=False):
    now_text = _now().isoformat(timespec="seconds")
    with _DB_LOCK, _db() as conn:
        if ok:
            repeat = reminder.get("repeat_interval") or "none"
            if manual:
                conn.execute(
                    "UPDATE reminders SET last_delivered_at = ?, last_error = NULL, updated_at = ? WHERE id = ?",
                    (now_text, now_text, reminder["id"]),
                )
            elif repeat == "none":
                conn.execute(
                    """
                    UPDATE reminders
                    SET status = 'completed', last_delivered_at = ?, last_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_text, now_text, reminder["id"]),
                )
            else:
                current = datetime.fromisoformat(reminder["trigger_at"])
                next_at = _next_trigger(current, repeat)
                while next_at and next_at <= _now():
                    next_at = _next_trigger(next_at, repeat)
                conn.execute(
                    """
                    UPDATE reminders
                    SET trigger_at = ?, status = 'active', last_delivered_at = ?, last_error = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_at.isoformat(timespec="seconds"), now_text, now_text, reminder["id"]),
                )
        else:
            conn.execute(
                """
                UPDATE reminders
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(response)[:1000], now_text, reminder["id"]),
            )
        conn.commit()


def _fire_reminder(reminder, manual=False):
    ok, response = _deliver(reminder)
    _mark_delivery(reminder, ok, response, manual=manual)
    return ok, response


def _due_reminders():
    now_text = _now().isoformat(timespec="seconds")
    with _DB_LOCK, _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE status = 'active' AND trigger_at <= ?
            ORDER BY trigger_at ASC
            LIMIT 20
            """,
            (now_text,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _scheduler_loop():
    _console(f"[reminders] scheduler started interval={CHECK_INTERVAL_SECONDS}s db={DB_FILE}")
    while True:
        try:
            for reminder in _due_reminders():
                ok, response = _fire_reminder(reminder)
                if not ok:
                    _console(f"[reminders] delivery failed id={reminder.get('id')}: {response}")
        except Exception as exc:
            _console(f"[reminders] scheduler error: {type(exc).__name__}: {exc}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def _start_scheduler():
    global _SCHEDULER_THREAD
    with _SCHEDULER_LOCK:
        if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, name="reminders-scheduler", daemon=True)
        _SCHEDULER_THREAD.start()


@reminders_bp.route("/reminders/create", methods=["POST"])
def route_reminders_create():
    data = _json_body()
    try:
        title = str(data.get("title") or "").strip()
        message = str(data.get("message") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400
        if not message:
            return jsonify({"error": "message is required"}), 400
        trigger_at = _parse_trigger_at(data.get("trigger_at"))
        repeat = _normalize_repeat(data.get("repeat"))
        delivered_to = _normalize_delivery(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    now_text = _now().isoformat(timespec="seconds")
    with _DB_LOCK, _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO reminders
            (title, message, trigger_at, repeat_interval, delivered_to, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (title, message, trigger_at.isoformat(timespec="seconds"), repeat, delivered_to, now_text, now_text),
        )
        conn.commit()
        reminder_id = cur.lastrowid
    return jsonify({"status": "created", "reminder": _load_reminder(reminder_id)})


@reminders_bp.route("/reminders/list", methods=["GET"])
def route_reminders_list():
    with _DB_LOCK, _db() as conn:
        rows = conn.execute("SELECT * FROM reminders ORDER BY trigger_at ASC, id ASC").fetchall()
    reminders = [_row_to_dict(row) for row in rows]
    return jsonify({"reminders": reminders, "count": len(reminders)})


@reminders_bp.route("/reminders/upcoming", methods=["GET"])
def route_reminders_upcoming():
    with _DB_LOCK, _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE status = 'active'
            ORDER BY trigger_at ASC, id ASC
            LIMIT 5
            """
        ).fetchall()
    reminders = [_row_to_dict(row) for row in rows]
    return jsonify({"reminders": reminders, "count": len(reminders)})


@reminders_bp.route("/reminders/<int:reminder_id>/snooze", methods=["POST"])
def route_reminders_snooze(reminder_id):
    data = _json_body()
    try:
        minutes = max(1, min(int(data.get("minutes", 15)), 24 * 60))
    except (TypeError, ValueError):
        minutes = 15
    trigger_at = (_now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    now_text = _now().isoformat(timespec="seconds")
    with _DB_LOCK, _db() as conn:
        cur = conn.execute(
            """
            UPDATE reminders
            SET trigger_at = ?, status = 'active', last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (trigger_at, now_text, reminder_id),
        )
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "reminder not found", "id": reminder_id}), 404
    return jsonify({"status": "snoozed", "minutes": minutes, "reminder": _load_reminder(reminder_id)})


@reminders_bp.route("/reminders/<int:reminder_id>", methods=["DELETE"])
def route_reminders_delete(reminder_id):
    now_text = _now().isoformat(timespec="seconds")
    with _DB_LOCK, _db() as conn:
        cur = conn.execute(
            "UPDATE reminders SET status = 'canceled', updated_at = ? WHERE id = ?",
            (now_text, reminder_id),
        )
        conn.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "reminder not found", "id": reminder_id}), 404
    return jsonify({"status": "canceled", "reminder": _load_reminder(reminder_id)})


@reminders_bp.route("/reminders/trigger/<int:reminder_id>", methods=["POST"])
def route_reminders_trigger(reminder_id):
    reminder = _load_reminder(reminder_id)
    if not reminder:
        return jsonify({"error": "reminder not found", "id": reminder_id}), 404
    ok, response = _fire_reminder(reminder, manual=True)
    payload = {
        "status": "delivered" if ok else "failed",
        "id": reminder_id,
        "response": response,
        "reminder": _load_reminder(reminder_id),
    }
    return jsonify(payload), 200 if ok else 502


def _auth_blueprint(bp, require_auth):
    for endpoint, view_func in list(bp.view_functions.items()):
        if getattr(view_func, "_hermes_auth_wrapped", False):
            continue
        wrapped = require_auth(view_func)
        wrapped._hermes_auth_wrapped = True
        bp.view_functions[endpoint] = wrapped


def register_routes(app, state, require_auth):
    _init_db()
    _auth_blueprint(reminders_bp, require_auth)
    app.register_blueprint(reminders_bp)
    _start_scheduler()
    state.reminders = {"db": str(DB_FILE), "interval_seconds": CHECK_INTERVAL_SECONDS}
