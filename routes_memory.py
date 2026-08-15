"""Persistent cross-session memory routes backed by SQLite FTS5."""

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from shared import COAGENT_DIR, _json_body


MEMORY_DB = COAGENT_DIR / "memory.db"
_DB_LOCK = threading.RLock()
_DB_READY = False


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect():
    conn = sqlite3.connect(str(MEMORY_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _check_fts5(conn):
    options = {str(row[0]).upper() for row in conn.execute("PRAGMA compile_options")}
    if "ENABLE_FTS5" not in options:
        raise RuntimeError("SQLite FTS5 is not enabled in this Python build")


def _init_db(conn):
    global _DB_READY
    if _DB_READY:
        # Verify tables still exist — the DB file may have been deleted/replaced.
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        if row:
            return
        _DB_READY = False
    _check_fts5(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT,
            tags TEXT
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            tags TEXT
        );

        CREATE TABLE IF NOT EXISTS facts_archive (
            id INTEGER PRIMARY KEY,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT,
            tags TEXT,
            archived_at TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            kind UNINDEXED,
            ref_id UNINDEXED,
            key,
            value,
            source UNINDEXED,
            tags,
            created_at UNINDEXED,
            updated_at UNINDEXED
        );
        """
    )
    _rebuild_fts_if_empty(conn)
    conn.commit()
    _DB_READY = True
    # Enforce the 90-day retention policy once per process start.
    try:
        archived = _archive_old_facts(conn)
        conn.commit()
        if archived:
            from shared import _log
            _log(f"[memory] archived {archived} stale fact(s)")
    except Exception as e:
        from shared import _log
        _log(f"[memory] archive sweep failed: {type(e).__name__}: {e}")


def _rebuild_fts_if_empty(conn):
    fts_count = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
    if fts_count:
        return
    for row in conn.execute("SELECT * FROM facts"):
        _upsert_fts_fact(conn, row)
    for row in conn.execute("SELECT * FROM notes"):
        _upsert_fts_note(conn, row)


def _tag_text(tags):
    if tags is None:
        return ""
    if isinstance(tags, str):
        values = [item.strip() for item in tags.split(",")]
    elif isinstance(tags, list):
        values = [str(item).strip() for item in tags]
    else:
        raise ValueError("tags must be a string or list")
    return ",".join(item for item in values if item)


def _tag_set(tags):
    return {item.strip().lower() for item in (tags or "").split(",") if item.strip()}


def _value_text(value):
    if value is None:
        raise ValueError("value is required")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fact_payload(row):
    return {
        "id": row["id"],
        "key": row["key"],
        "value": row["value"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source": row["source"] or "",
        "tags": row["tags"] or "",
    }


def _note_payload(row):
    return {
        "id": row["id"],
        "content": row["content"],
        "created_at": row["created_at"],
        "tags": row["tags"] or "",
    }


def _delete_fts(conn, kind, ref_id):
    conn.execute("DELETE FROM memory_fts WHERE kind = ? AND ref_id = ?", (kind, str(ref_id)))


def _upsert_fts_fact(conn, row):
    _delete_fts(conn, "fact", row["id"])
    conn.execute(
        """
        INSERT INTO memory_fts(kind, ref_id, key, value, source, tags, created_at, updated_at)
        VALUES('fact', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(row["id"]),
            row["key"],
            row["value"],
            row["source"] or "",
            row["tags"] or "",
            row["created_at"],
            row["updated_at"],
        ),
    )


def _upsert_fts_note(conn, row):
    _delete_fts(conn, "note", row["id"])
    conn.execute(
        """
        INSERT INTO memory_fts(kind, ref_id, key, value, source, tags, created_at, updated_at)
        VALUES('note', ?, '', ?, '', ?, ?, ?)
        """,
        (
            str(row["id"]),
            row["content"],
            row["tags"] or "",
            row["created_at"],
            row["created_at"],
        ),
    )


def _archive_old_facts(conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).replace(microsecond=0)
    cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
    archived_at = _now()
    rows = conn.execute("SELECT * FROM facts WHERE updated_at < ?", (cutoff_text,)).fetchall()
    count = 0
    for row in rows:
        if "permanent" in _tag_set(row["tags"]):
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO facts_archive
            (id, key, value, created_at, updated_at, source, tags, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["key"],
                row["value"],
                row["created_at"],
                row["updated_at"],
                row["source"],
                row["tags"],
                archived_at,
            ),
        )
        conn.execute("DELETE FROM facts WHERE id = ?", (row["id"],))
        _delete_fts(conn, "fact", row["id"])
        count += 1
    return count


@contextmanager
def _db():
    with _DB_LOCK:
        conn = _connect()
        try:
            _init_db(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _db_error(exc):
    from shared import _log
    _log(f"[memory] database error: {type(exc).__name__}: {exc}")
    return jsonify({"error": "internal database error"}), 500


def _limit(default=20, maximum=200):
    raw = request.args.get("limit", default)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _fts_query(text):
    terms = re.findall(r"[\w'-]+", text or "", flags=re.UNICODE)
    terms = [term.strip("'-") for term in terms if term.strip("'-")]
    if not terms:
        raise ValueError("q must include at least one searchable term")
    return " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms[:20])


def memory_stats():
    try:
        with _db() as conn:
            facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            archived = conn.execute("SELECT COUNT(*) FROM facts_archive").fetchone()[0]
            fts_rows = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        return {
            "facts": facts,
            "notes": notes,
            "archived_facts": archived,
            "fts_rows": fts_rows,
            "db_path": str(MEMORY_DB),
            "db_size_bytes": MEMORY_DB.stat().st_size if MEMORY_DB.exists() else 0,
            "fts5": True,
        }
    except Exception as exc:
        return {
            "facts": 0,
            "notes": 0,
            "archived_facts": 0,
            "fts_rows": 0,
            "db_path": str(MEMORY_DB),
            "db_size_bytes": MEMORY_DB.stat().st_size if MEMORY_DB.exists() else 0,
            "fts5": False,
            "error": str(exc),
        }


def register_routes(app, state, require_auth):
    @app.route("/memory/fact", methods=["POST"])
    @require_auth
    def route_memory_fact_save():
        data = _json_body()
        key = data.get("key")
        if not isinstance(key, str) or not key.strip():
            return jsonify({"error": "key is required"}), 400
        try:
            value = _value_text(data.get("value"))
            tags = _tag_text(data.get("tags"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        source = data.get("source")
        source = str(source).strip() if source is not None else ""
        now = _now()
        try:
            with _db() as conn:
                existing = conn.execute("SELECT id, created_at FROM facts WHERE key = ?", (key.strip(),)).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE facts
                        SET value = ?, updated_at = ?, source = ?, tags = ?
                        WHERE id = ?
                        """,
                        (value, now, source, tags, existing["id"]),
                    )
                    fact_id = existing["id"]
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO facts(key, value, created_at, updated_at, source, tags)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (key.strip(), value, now, now, source, tags),
                    )
                    fact_id = cur.lastrowid
                row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
                _upsert_fts_fact(conn, row)
                return jsonify({"status": "saved", "fact": _fact_payload(row)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/fact", methods=["GET"])
    @require_auth
    def route_memory_fact_get():
        key = request.args.get("key", "")
        if not key:
            return jsonify({"error": "key is required"}), 400
        try:
            with _db() as conn:
                row = conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "fact not found", "key": key}), 404
                return jsonify({"fact": _fact_payload(row)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/store", methods=["POST"])
    @require_auth
    def route_memory_store():
        data = _json_body()
        key = data.get("key")
        if not isinstance(key, str) or not key.strip():
            return jsonify({"error": "key is required"}), 400
        try:
            value = _value_text(data.get("value"))
            tags = _tag_text(data.get("tags"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        source = data.get("source")
        source = str(source).strip() if source is not None else ""
        now = _now()
        try:
            with _db() as conn:
                existing = conn.execute("SELECT id, created_at FROM facts WHERE key = ?", (key.strip(),)).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE facts
                        SET value = ?, updated_at = ?, source = ?, tags = ?
                        WHERE id = ?
                        """,
                        (value, now, source, tags, existing["id"]),
                    )
                    fact_id = existing["id"]
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO facts(key, value, created_at, updated_at, source, tags)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (key.strip(), value, now, now, source, tags),
                    )
                    fact_id = cur.lastrowid
                row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
                _upsert_fts_fact(conn, row)
                return jsonify({"status": "stored", "key": row["key"], "value": row["value"], "fact": _fact_payload(row)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/recall/<path:key>", methods=["GET"])
    @require_auth
    def route_memory_recall(key):
        try:
            with _db() as conn:
                row = conn.execute("SELECT * FROM facts WHERE key = ?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "fact not found", "key": key}), 404
                return jsonify({"key": row["key"], "value": row["value"], "fact": _fact_payload(row)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/note", methods=["POST"])
    @require_auth
    def route_memory_note_save():
        data = _json_body()
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "content is required"}), 400
        try:
            tags = _tag_text(data.get("tags"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        now = _now()
        try:
            with _db() as conn:
                cur = conn.execute(
                    "INSERT INTO notes(content, created_at, tags) VALUES (?, ?, ?)",
                    (content.strip(), now, tags),
                )
                row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
                _upsert_fts_note(conn, row)
                return jsonify({"status": "saved", "note": _note_payload(row)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/search", methods=["GET"])
    @require_auth
    def route_memory_search():
        q = request.args.get("q", "")
        if not q.strip():
            return jsonify({"error": "q is required"}), 400
        try:
            query = _fts_query(q)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            with _db() as conn:
                rows = conn.execute(
                    """
                    SELECT kind, ref_id, key, value, source, tags, created_at, updated_at,
                           bm25(memory_fts) AS score
                    FROM memory_fts
                    WHERE memory_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (query, _limit(default=20, maximum=100)),
                ).fetchall()
                results = []
                for row in rows:
                    item = {
                        "type": row["kind"],
                        "id": int(row["ref_id"]),
                        "key": row["key"] or "",
                        "content": row["value"] or "",
                        "source": row["source"] or "",
                        "tags": row["tags"] or "",
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "score": row["score"],
                    }
                    results.append(item)
                return jsonify({"query": q, "results": results, "count": len(results)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/recent", methods=["GET"])
    @require_auth
    def route_memory_recent():
        try:
            with _db() as conn:
                rows = conn.execute(
                    """
                    SELECT 'fact' AS kind, id, key, value AS content, created_at, updated_at, source, tags
                    FROM facts
                    UNION ALL
                    SELECT 'note' AS kind, id, '' AS key, content, created_at, created_at AS updated_at,
                           '' AS source, tags
                    FROM notes
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (_limit(default=20, maximum=200),),
                ).fetchall()
                entries = [dict(row) for row in rows]
                return jsonify({"entries": entries, "count": len(entries)})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/fact/<int:fact_id>", methods=["DELETE"])
    @require_auth
    def route_memory_fact_delete(fact_id):
        try:
            with _db() as conn:
                cur = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
                if cur.rowcount == 0:
                    return jsonify({"error": "fact not found", "id": fact_id}), 404
                _delete_fts(conn, "fact", fact_id)
                return jsonify({"status": "deleted", "id": fact_id})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/note/<int:note_id>", methods=["DELETE"])
    @require_auth
    def route_memory_note_delete(note_id):
        try:
            with _db() as conn:
                cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
                if cur.rowcount == 0:
                    return jsonify({"error": "note not found", "id": note_id}), 404
                _delete_fts(conn, "note", note_id)
                return jsonify({"status": "deleted", "id": note_id})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/forget/<path:key>", methods=["POST"])
    @require_auth
    def route_memory_forget(key):
        try:
            with _db() as conn:
                row = conn.execute("SELECT id FROM facts WHERE key = ?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "fact not found", "key": key}), 404
                fact_id = row["id"]
                conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
                _delete_fts(conn, "fact", fact_id)
                return jsonify({"status": "forgotten", "key": key})
        except (sqlite3.Error, RuntimeError) as exc:
            return _db_error(exc)

    @app.route("/memory/stats", methods=["GET"])
    @require_auth
    def route_memory_stats():
        return jsonify(memory_stats())

    state.memory = {"db_path": str(MEMORY_DB), "stats": memory_stats}
