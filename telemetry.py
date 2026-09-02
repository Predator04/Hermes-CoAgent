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
    db = None
    try:
        db = sqlite3.connect(str(TELEMETRY_DB_PATH), timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        return db
    except Exception as e:
        _LOGGER.error("Telemetry DB connect failed: %s", e)
        if db is not None:
            db.close()
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
        # migrate databases that predate the strategy columns FIRST — the index
        # creation below references these columns, so it must come after the ALTER
        # (on a fresh DB the ALTER fails with "no such table" and is skipped).
        for _column in ("strategy", "app", "element_type"):
            try:
                db.execute(f"ALTER TABLE actions ADD COLUMN {_column} TEXT")
            except sqlite3.OperationalError:
                pass  # column already present (or table not created yet)
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
                session_id TEXT,
                strategy TEXT,
                app TEXT,
                element_type TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_actions_tool ON actions(tool);
            CREATE INDEX IF NOT EXISTS idx_actions_success ON actions(success);
            CREATE INDEX IF NOT EXISTS idx_actions_strategy ON actions(app, element_type, strategy);
        """)
        db.commit()
        _LOGGER.info("Telemetry DB initialized at %s", TELEMETRY_DB_PATH)
        return True
    except Exception as e:
        _LOGGER.error("Telemetry DB init failed: %s", e)
        # Don't leave a half-initialized DB path set — otherwise every later
        # log_action/endpoint call queries a schema that was never created.
        TELEMETRY_DB_PATH = None
        return False
    finally:
        db.close()


def log_action(tool, endpoint=None, input_summary=None, success=True,
               status_code=200, duration_ms=0, error_message=None,
               screenshot_before=None, screenshot_after=None, session_id=None,
               strategy=None, app=None, element_type=None):
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
                duration_ms, error_message, screenshot_before, screenshot_after,
                session_id, strategy, app, element_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tool, endpoint, input_summary, 1 if success else 0,
             status_code, duration_ms, error_message,
             screenshot_before, screenshot_after, session_id,
             strategy, app, element_type)
        )
        db.commit()
        return True
    except Exception as e:
        _LOGGER.error("Telemetry log_action failed: %s", e)
        return False
    finally:
        db.close()


def log_find(app, element_type, strategy, success=True, duration_ms=0, error_message=None):
    """Log an element-find attempt: which strategy was tried and whether it won."""
    app = str(app or "").strip()[:120]
    element_type = str(element_type or "").strip()[:80]
    strategy = str(strategy or "").strip()[:60]
    if not strategy:
        return False
    return log_action(
        tool="find",
        input_summary=f"{app}:{element_type}:{strategy}"[:200],
        success=success,
        duration_ms=int(duration_ms or 0),
        error_message=error_message,
        strategy=strategy,
        app=app,
        element_type=element_type,
    )


def get_best_strategy(app, element_type, min_samples=2):
    """Return the historically most successful find strategy for app+element_type.

    Ranks by success rate, then lower average duration, preferring strategies
    with at least ``min_samples`` observations. Empty app/element_type are exact
    keys (both empty = global best).
    """
    db = _get_db()
    if db is None:
        return {"strategy": None, "reason": "telemetry unavailable", "samples": 0}
    try:
        app = str(app or "").strip()
        element_type = str(element_type or "").strip()
        where = ["strategy IS NOT NULL", "strategy != ''"]
        params = []
        if app:
            where.append("app = ?")
            params.append(app)
        if element_type:
            where.append("element_type = ?")
            params.append(element_type)
        rows = db.execute(
            """SELECT strategy, COUNT(*) AS n,
                      COALESCE(SUM(success), 0) AS ok,
                      COALESCE(AVG(duration_ms), 0) AS avg_ms
               FROM actions
               WHERE """ + " AND ".join(where) + """
               GROUP BY strategy
               ORDER BY n DESC""",
            params,
        ).fetchall()
        if not rows:
            return {"strategy": None, "reason": "no telemetry for app+element_type", "samples": 0}
        scored = []
        for row in rows:
            n = int(row["n"] or 0)
            ok = int(row["ok"] or 0)
            scored.append({
                "strategy": row["strategy"],
                "samples": n,
                "success_rate": round(ok / n, 3) if n else 0.0,
                "avg_duration_ms": round(float(row["avg_ms"] or 0), 1),
            })
        try:
            min_samples = max(1, int(min_samples))
        except (TypeError, ValueError):
            min_samples = 2
        qualified = [s for s in scored if s["samples"] >= min_samples]
        pool = qualified or scored
        pool.sort(key=lambda s: (-s["success_rate"], s["avg_duration_ms"], -s["samples"]))
        best = pool[0]
        return {
            "strategy": best["strategy"],
            "samples": best["samples"],
            "success_rate": best["success_rate"],
            "avg_duration_ms": best["avg_duration_ms"],
            "strategies": scored,
            "reason": "ok",
        }
    except Exception as e:
        _LOGGER.error("get_best_strategy failed: %s", e)
        return {"strategy": None, "reason": f"error: {e}", "samples": 0}
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
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 500))
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            return jsonify({"error": "limit and offset must be integers"}), 400
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
                "strategy": row["strategy"],
                "app": row["app"],
                "element_type": row["element_type"],
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


@telem_bp.route("/telemetry/best-strategy", methods=["GET"])
def get_best_strategy_endpoint():
    """Return the historically best find strategy for an app + element type."""
    app = (request.args.get("app") or "").strip()
    element_type = (request.args.get("element_type") or request.args.get("type") or "").strip()
    if not app and not element_type:
        return jsonify({"error": "app or element_type query parameter is required"}), 400
    try:
        min_samples = int(request.args.get("min_samples", 2))
    except (TypeError, ValueError):
        min_samples = 2
    result = get_best_strategy(app, element_type, min_samples=min_samples)
    result["app"] = app
    result["element_type"] = element_type
    return jsonify(result)
