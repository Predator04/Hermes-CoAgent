"""Clipboard history manager routes.

Endpoints:
  GET/POST /clipboard/history - list recent clipboard entries (search + filter)
  GET/POST /clipboard/get     - read current clipboard contents (and record it)
  POST     /clipboard/set     - set the system clipboard to a given text value
  POST     /clipboard/pin     - pin, unpin, or delete a stored entry by id

A background poller watches the Windows clipboard for changes and appends new
text entries to an in-memory ring buffer. Pinned entries are exempt from the
history cap so they persist across the buffer's LRU eviction. Windows-only
dependencies (win32clipboard, ctypes user32) are imported inside try/except so
the Linux syntax-check CI stays green; endpoints fall back to HTTP 501 when the
runtime cannot access the clipboard.
"""

import hashlib
import os
import threading
import time

from flask import jsonify

from shared import _json_body, _log, _missing_field


# ---------------------------------------------------------------------------
# Optional Windows-only imports
# ---------------------------------------------------------------------------
_CLIPBOARD_BACKEND = None
_CLIPBOARD_IMPORT_ERROR = None

try:
    import win32clipboard  # type: ignore
    import win32con  # type: ignore
    _CLIPBOARD_BACKEND = "pywin32"
except Exception as _exc:  # ImportError on Linux, DLL errors elsewhere
    win32clipboard = None
    win32con = None
    _CLIPBOARD_IMPORT_ERROR = str(_exc)

if _CLIPBOARD_BACKEND is None and os.name == "nt":
    try:
        import ctypes  # noqa: F401
        from ctypes import wintypes  # noqa: F401
        _CLIPBOARD_BACKEND = "ctypes"
        _CLIPBOARD_IMPORT_ERROR = None
    except Exception as _exc:  # noqa: BLE001
        _CLIPBOARD_IMPORT_ERROR = str(_exc)


# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
_MAX_HISTORY = 200
_POLL_INTERVAL = 1.0
_MAX_TEXT_BYTES = 1_000_000  # 1 MB cap on stored entries

_STATE_LOCK = threading.Lock()
_HISTORY = []              # list[dict] oldest first
_HISTORY_BY_ID = {}        # entry_id -> dict
_PINNED_IDS = set()        # set of pinned entry ids

_POLLER_STARTED = False
_POLLER_LOCK = threading.Lock()
_LAST_HASH = None


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (clipboard backend unavailable)"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _backend_available():
    return os.name == "nt" and _CLIPBOARD_BACKEND is not None


# ---------------------------------------------------------------------------
# Clipboard read/write helpers
# ---------------------------------------------------------------------------
def _open_clipboard(retries=6, delay=0.05):
    """Open the Windows clipboard with a few retries for common contention."""
    last_exc = None
    for _ in range(max(1, retries)):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return False


def _read_clipboard_text():
    """Return the current clipboard text (Unicode) or None if empty/not-text."""
    if _CLIPBOARD_BACKEND != "pywin32":
        return _read_clipboard_text_ctypes()
    try:
        _open_clipboard()
    except Exception as exc:  # noqa: BLE001
        _log(f"clipboard: open failed: {exc}")
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return data if isinstance(data, str) else None
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_TEXT)
            if isinstance(data, bytes):
                try:
                    return data.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    return None
            return data if isinstance(data, str) else None
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def _write_clipboard_text(text):
    if _CLIPBOARD_BACKEND != "pywin32":
        return _write_clipboard_text_ctypes(text)
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def _read_clipboard_text_ctypes():
    """ctypes fallback used when pywin32 is missing but we're on Windows."""
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not user32.OpenClipboard(0):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            return ctypes.c_wchar_p(locked).value
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return None


def _write_clipboard_text_ctypes(text):
    import ctypes
    from ctypes import wintypes  # noqa: F401

    GMEM_MOVEABLE = 0x0002
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not isinstance(text, str):
        text = str(text or "")
    encoded = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(encoded)

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise OSError("GlobalAlloc failed")
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise OSError("GlobalLock failed")
    ctypes.memmove(locked, encoded, size)
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(0):
        kernel32.GlobalFree(handle)
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# History bookkeeping
# ---------------------------------------------------------------------------
def _entry_id(text):
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def _record_text(text, source="poll"):
    """Insert clipboard text into history. Returns (entry, is_new)."""
    global _LAST_HASH
    if not isinstance(text, str) or not text:
        return None, False
    if len(text.encode("utf-8", errors="replace")) > _MAX_TEXT_BYTES:
        text = text[:_MAX_TEXT_BYTES]

    eid = _entry_id(text)
    now = time.time()

    with _STATE_LOCK:
        existing = _HISTORY_BY_ID.get(eid)
        if existing is not None:
            existing["last_seen"] = now
            existing["hit_count"] = int(existing.get("hit_count", 0)) + 1
            # Bump to most-recent position without duplicating.
            try:
                _HISTORY.remove(existing)
            except ValueError:
                pass
            _HISTORY.append(existing)
            _LAST_HASH = eid
            return dict(existing), False

        entry = {
            "id": eid,
            "text": text,
            "length": len(text),
            "created": now,
            "last_seen": now,
            "hit_count": 1,
            "pinned": eid in _PINNED_IDS,
            "source": source,
        }
        _HISTORY.append(entry)
        _HISTORY_BY_ID[eid] = entry
        _evict_locked()
        _LAST_HASH = eid
        return dict(entry), True


def _evict_locked():
    """LRU-evict unpinned entries when over the cap. Must hold _STATE_LOCK."""
    overflow = len(_HISTORY) - _MAX_HISTORY
    if overflow <= 0:
        return
    kept = []
    removed = 0
    for entry in _HISTORY:
        if removed < overflow and not entry.get("pinned"):
            _HISTORY_BY_ID.pop(entry["id"], None)
            removed += 1
            continue
        kept.append(entry)
    _HISTORY[:] = kept


def _snapshot_history(query=None, pinned_only=False, limit=None):
    with _STATE_LOCK:
        entries = list(_HISTORY)
    if pinned_only:
        entries = [e for e in entries if e.get("pinned")]
    if query:
        needle = query.lower()
        entries = [e for e in entries if needle in (e.get("text") or "").lower()]
    entries.sort(key=lambda e: (0 if e.get("pinned") else 1, -float(e.get("last_seen", 0))))
    if isinstance(limit, int) and limit > 0:
        entries = entries[:limit]
    return [dict(e) for e in entries]


# ---------------------------------------------------------------------------
# Background poller
# ---------------------------------------------------------------------------
def _poll_loop():
    global _LAST_HASH
    while True:
        try:
            text = _read_clipboard_text()
            if text is not None and text != "":
                eid = _entry_id(text)
                if eid != _LAST_HASH:
                    _record_text(text, source="poll")
        except Exception as exc:  # noqa: BLE001
            _log(f"clipboard: poll error: {exc}")
        time.sleep(_POLL_INTERVAL)


def _ensure_poller():
    global _POLLER_STARTED
    if _POLLER_STARTED or not _backend_available():
        return
    with _POLLER_LOCK:
        if _POLLER_STARTED:
            return
        threading.Thread(target=_poll_loop, name="clipboard-poller", daemon=True).start()
        _POLLER_STARTED = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def register_routes(app, state, require_auth):

    @app.route("/clipboard/history", methods=["GET", "POST"])
    @require_auth
    def route_clipboard_history():
        if not _backend_available():
            return _windows_only(_CLIPBOARD_IMPORT_ERROR)

        _ensure_poller()

        body = _json_body()
        query = None
        pinned_only = False
        limit = None
        if isinstance(body, dict):
            q = body.get("query") or body.get("q")
            if isinstance(q, str) and q.strip():
                query = q.strip()
            pinned_only = bool(body.get("pinned_only") or body.get("pinned"))
            raw_limit = body.get("limit")
            if isinstance(raw_limit, int) and raw_limit > 0:
                limit = min(raw_limit, _MAX_HISTORY)

        entries = _snapshot_history(query=query, pinned_only=pinned_only, limit=limit)
        with _STATE_LOCK:
            total = len(_HISTORY)
            pinned = sum(1 for e in _HISTORY if e.get("pinned"))
        return jsonify({
            "count": len(entries),
            "total": total,
            "pinned_count": pinned,
            "max_history": _MAX_HISTORY,
            "entries": entries,
        })

    @app.route("/clipboard/history/get", methods=["GET", "POST"])
    @require_auth
    def route_clipboard_history_get():
        if not _backend_available():
            return _windows_only(_CLIPBOARD_IMPORT_ERROR)

        _ensure_poller()
        try:
            text = _read_clipboard_text()
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"clipboard read failed: {exc}"}), 500

        if text is None:
            return jsonify({
                "status": "ok",
                "text": None,
                "empty": True,
                "recorded": False,
            })

        entry, is_new = _record_text(text, source="get")
        return jsonify({
            "status": "ok",
            "text": text,
            "empty": text == "",
            "recorded": bool(entry) and is_new,
            "entry": entry,
        })

    @app.route("/clipboard/history/set", methods=["POST"])
    @require_auth
    def route_clipboard_history_set():
        if not _backend_available():
            return _windows_only(_CLIPBOARD_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        # Allow selecting a stored entry by id, or providing raw text.
        entry_id = body.get("id") or body.get("entry_id")
        text = body.get("text")

        if entry_id and not text:
            with _STATE_LOCK:
                existing = _HISTORY_BY_ID.get(entry_id)
            if existing is None:
                return jsonify({"error": "unknown entry id"}), 404
            text = existing.get("text", "")

        if text is None:
            return _missing_field("text")
        if not isinstance(text, str):
            return jsonify({"error": "text must be a string"}), 400
        if len(text.encode("utf-8", errors="replace")) > _MAX_TEXT_BYTES:
            return jsonify({"error": "text exceeds size limit"}), 413

        try:
            _write_clipboard_text(text)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"clipboard write failed: {exc}"}), 500

        entry, _ = _record_text(text, source="set")
        _log(f"clipboard/set len={len(text)} id={entry['id'] if entry else '-'}")
        return jsonify({
            "status": "ok",
            "length": len(text),
            "entry": entry,
        })

    @app.route("/clipboard/pin", methods=["POST"])
    @require_auth
    def route_clipboard_pin():
        if not _backend_available():
            return _windows_only(_CLIPBOARD_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        entry_id = body.get("id") or body.get("entry_id")
        if not entry_id:
            return _missing_field("id")

        action = (body.get("action") or "pin").lower()
        if action not in ("pin", "unpin", "toggle", "delete"):
            return jsonify({"error": "action must be one of: pin, unpin, toggle, delete"}), 400

        with _STATE_LOCK:
            entry = _HISTORY_BY_ID.get(entry_id)
            if entry is None:
                return jsonify({"error": "unknown entry id"}), 404

            if action == "delete":
                _PINNED_IDS.discard(entry_id)
                _HISTORY_BY_ID.pop(entry_id, None)
                try:
                    _HISTORY.remove(entry)
                except ValueError:
                    pass
                result = {"status": "ok", "deleted": True, "id": entry_id}
            else:
                if action == "pin":
                    pinned = True
                elif action == "unpin":
                    pinned = False
                else:  # toggle
                    pinned = not bool(entry.get("pinned"))
                entry["pinned"] = pinned
                if pinned:
                    _PINNED_IDS.add(entry_id)
                else:
                    _PINNED_IDS.discard(entry_id)
                result = {
                    "status": "ok",
                    "id": entry_id,
                    "pinned": pinned,
                    "entry": dict(entry),
                }
            total_pinned = sum(1 for e in _HISTORY if e.get("pinned"))
        result["pinned_count"] = total_pinned
        _log(f"clipboard/pin id={entry_id} action={action}")
        return jsonify(result)
