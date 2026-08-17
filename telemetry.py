"""Hermes CoAgent v8.2 — SQLite Action Telemetry.

Logs every agent action (tool, endpoint, success/fail, duration)
to a structured SQLite database for analytics and debugging.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()

TELEMETRY_DB_PATH = None
_WARNED = False

telem_bp = Blueprint("telemetry", __name__)


def _get_db():
    """Get a thread-safe connection to the telemetry database."""
    global _WARNED
    if TELEMETRY_DB_PATH is None:
        if not _WARNED:
            _LOGGER.warning("Telemetry DB not initialized (call init_telemetry first)")
            _WARNED = True
        return None
    try:
        db = sqlite3.connect(str(TELEMETRY_DB_PATH), timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        return db
    except Exception as e:
        _LOGGER.error("Telemetry DB connect failed: %s", e)
        return None


def init_telem(db_dir=None):
    """Initialize the telemetry database. Call at startup."""
    global TELEMETRY_DB_PATH, _WARNED
    if db_dir is None:
        db_dir = Path(__file__).parent.resolve()
    db_path = Path(db_dir)
    try:
        db_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        _LOGGER.error("Cannot create telemetry DB directory: %s", db_path)
        return False
    TELEMETRY_DB_PATH = db_path / "telemetry.db"
    _WARNED = False
    db = _get_db()
    if db is None:
        _LOGGER.error("Failed to open telemetry DB at %s", TELEMETRY_DB_PATH)
        return False
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                tool TEXT NOT NULL,
                endpoint TEXT,
                input_summary TEXT,
                success BOOLEAN NOT NULL DEFAULT 1,
                status_code INTEGER,
                duration_ms INTEGER DEFAULT 0,
                error_message TEXT,
                screenshot_before TEXT,
                screenshot_after TEXT,
                session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_actions_tool ON actions(tool);
            CREATE INDEX IF NOT EXISTS idx_actions_success ON actions(success);
        """)
        db.commit()
        _LOGGER.info("Telemetry DB initialized at %s", TELEMETRY_DB_PATH)
        return True
    except Exception as e:
        _LOGGER.error("Telemetry DB init failed: %s", e)
        return False
    finally:
        db.close()


def log_action(tool, endpoint=None, input_summary=None, success=True,
               status_code=200, duration_ms=0, error_message=None,
               screenshot_before=None, screenshot_after=None, session_id=None):
    """Log an action to the telemetry database."""
    db = _get_db()
    if db is None:
        return False
    try:
        if input_summary and len(input_summary) > 200:
            input_summary = input_summary[:200]
        db.execute(
            """INSERT INTO actions
               (tool, endpoint, input_summary, success, status_code,
                duration_ms, error_message, screenshot_before, screenshot_after, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tool, endpoint, input_summary, 1 if success else 0,
             status_code, duration_ms, error_message,
             screenshot_before, screenshot_after, session_id)
        )
        db.commit()
        return True
    except Exception as e:
        _LOGGER.error("Telemetry log_action failed: %s", e)
        return False
    finally:
        db.close()


# ── Flask endpoints ──────────────────────────────────────────────────────


@telem_bp.route("/telemetry", methods=["GET"])
def get_telemetry():
    """List recent actions with pagination and filters."""
    db = _get_db()
    if db is None:
        return jsonify({"error": "Telemetry not initialized"}), 500

    try:
        limit = min(int(request.args.get("limit", 50)), 500)
        offset = int(request.args.get("offset", 0))
        tool_filter = request.args.get("tool")
        success_filter = request.args.get("success")
        since = request.args.get("since")
        where_clauses = []
        params = []
        if tool_filter:
            where_clauses.append("tool = ?")
            params.append(tool_filter)
        if success_filter is not None:
            val = 1 if success_filter.lower() in ("true", "1", "yes") else 0
            where_clauses.append("success = ?")
            params.append(val)
        if since:
            where_clauses.append("timestamp >= ?")
            params.append(since)

        where = ""
        if where_clauses:
            where = "WHERE " + " AND ".join(where_clauses)

        count_row = db.execute(f"SELECT COUNT(*) as cnt FROM actions {where}", params).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = db.execute(
            f"SELECT * FROM actions {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        actions = []
        for row in rows:
            actions.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "tool": row["tool"],
                "endpoint": row["endpoint"],
                "input_summary": row["input_summary"],
                "success": bool(row["success"]),
                "status_code": row["status_code"],
                "duration_ms": row["duration_ms"],
                "error_message": row["error_message"],
                "session_id": row["session_id"],
            })

        return jsonify({"actions": actions, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@telem_bp.route("/telemetry/stats", methods=["GET"])
def get_telemetry_stats():
    """Return aggregate telemetry statistics."""
    db = _get_db()
    if db is None:
        return jsonify({"error": "Telemetry not initialized"}), 500

    try:
        total = db.execute("SELECT COUNT(*) as c FROM actions").fetchone()["c"]
        success = db.execute("SELECT COUNT(*) as c FROM actions WHERE success=1").fetchone()["c"]
        today = db.execute(
            "SELECT COUNT(*) as c FROM actions WHERE timestamp >= datetime('now', '-1 day')"
        ).fetchone()["c"]
        avg_dur = db.execute("SELECT COALESCE(AVG(duration_ms), 0) as a FROM actions").fetchone()["a"]
        top_tools = db.execute(
            "SELECT tool, COUNT(*) as cnt FROM actions GROUP BY tool ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        return jsonify({
            "total_actions": total,
            "success_rate": round(success / total, 4) if total else 1.0,
            "actions_today": today,
            "avg_duration_ms": round(avg_dur, 1),
            "top_tools": [{"tool": r["tool"], "count": r["cnt"]} for r in top_tools],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
