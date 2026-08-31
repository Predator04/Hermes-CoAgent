"""Interactive terminal session control via Windows ConPTY.

Endpoints:
  POST /term/start  - spawn a new interactive shell (cmd.exe, powershell, wsl, ...)
  POST /term/write  - send input (keystrokes) to a running session
  POST /term/read   - drain buffered output produced since the last read
  POST /term/close  - terminate a session and free its resources

Streaming is implemented as a background reader thread per session that pushes
pty output into a bounded in-memory buffer; /term/read returns whatever has
accumulated. All prompt handling is left to the client - it simply sees the raw
byte stream (decoded as UTF-8 with error replacement).

The heavy lifting is done by pywinpty, which wraps the Windows ConPTY API.
On Linux the pywinpty import fails at module load, so it is wrapped in a
try/except and the endpoints degrade to HTTP 501 - this keeps the Linux
syntax-check CI green.

Any subprocess / shell command strings are pure ASCII per project rules.
"""

import os
import threading
import time
import uuid

from flask import jsonify

from shared import _json_body, _log, _missing_field


try:
    # pywinpty exposes ConPTY on Windows 10 1809+. Import is Windows-only.
    from winpty import PtyProcess as _PtyProcess  # type: ignore
    _PTY_IMPORT_ERROR = None
except Exception as _exc:  # ImportError on Linux, RuntimeError on old Windows
    _PtyProcess = None
    _PTY_IMPORT_ERROR = str(_exc)


# Session registry: session_id -> _Session
_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()

# Cap the per-session output buffer so a runaway process cannot exhaust RAM.
_MAX_BUFFER_BYTES = 4 * 1024 * 1024   # 4 MiB
_MAX_SESSIONS = 32
_DEFAULT_COLS = 120
_DEFAULT_ROWS = 30
_MAX_WRITE_BYTES = 64 * 1024
_MAX_READ_BYTES = 1024 * 1024


def _utf8_safe_head(buf, n):
    """Return a cut index >= n that lands on a UTF-8 codepoint boundary.

    When dropping the oldest bytes from the head of the output buffer, advance
    past any continuation bytes (0x80..0xBF) so we don't split a multi-byte
    character and leave a dangling continuation byte at the new head.
    """
    cut = n
    while cut < len(buf) and (buf[cut] & 0xC0) == 0x80:
        cut += 1
    return cut


def _utf8_safe_cut(buf, n):
    """Return a cut index <= n that lands on a UTF-8 codepoint boundary.

    When returning the newest n bytes, back up past any continuation bytes so
    the returned slice doesn't end mid-character. The partial character stays
    in the buffer for the next read.
    """
    cut = n
    while cut > 0 and (buf[cut - 1] & 0xC0) == 0x80:
        cut -= 1
    return cut


def _windows_only(detail=None):
    payload = {"error": "Windows-only endpoint (ConPTY unavailable)"}
    if detail:
        payload["detail"] = detail
    return jsonify(payload), 501


def _pty_available():
    return os.name == "nt" and _PtyProcess is not None


class _Session:
    """Wrap a pywinpty process with a bounded output buffer + reader thread."""

    def __init__(self, session_id, command, cols, rows, cwd=None, env=None):
        self.id = session_id
        self.command = command
        self.cols = cols
        self.rows = rows
        self.started_at = time.time()
        self.buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.closed = False
        self.exit_status = None
        self.read_error = None

        # pywinpty accepts either a list or a string; use a string to preserve
        # quoted arguments (e.g. "powershell.exe -NoProfile").
        cmdline = command if isinstance(command, str) else subprocess_join(command)
        self.pty = _PtyProcess.spawn(
            cmdline,
            dimensions=(int(rows), int(cols)),
            cwd=cwd,
            env=env,
        )
        self.pid = getattr(self.pty, "pid", None)

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"conpty-reader-{session_id}",
            daemon=True,
        )
        self._reader_thread.start()

    def _reader_loop(self):
        try:
            while True:
                # pywinpty read() returns str; encode to bytes for the buffer.
                try:
                    chunk = self.pty.read(4096)
                except EOFError:
                    break
                except OSError as exc:
                    self.read_error = str(exc)
                    break
                if not chunk:
                    if self.pty.isalive():
                        time.sleep(0.02)
                        continue
                    # Child has exited. Drain any final bytes still buffered in
                    # the ConPTY so trailing output (e.g. the exit message) is
                    # not dropped.
                    try:
                        chunk = self.pty.read(4096)
                    except Exception:
                        break
                    if not chunk:
                        break
                    # fall through to append the tail below
                if isinstance(chunk, str):
                    data = chunk.encode("utf-8", errors="replace")
                else:
                    data = bytes(chunk)
                with self.buffer_lock:
                    self.buffer.extend(data)
                    overflow = len(self.buffer) - _MAX_BUFFER_BYTES
                    if overflow > 0:
                        # Drop from the head so recent output survives, but only
                        # up to a UTF-8 boundary — a naive byte cut can split a
                        # multi-byte character and corrupt the remainder.
                        cut = _utf8_safe_head(self.buffer, overflow)
                        del self.buffer[:cut]
        finally:
            self.closed = True
            try:
                self.exit_status = self.pty.exitstatus
            except Exception:
                self.exit_status = None

    def write(self, data):
        if self.closed:
            raise OSError("session closed")
        # pywinpty write() takes str.
        text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        # pywinpty's underlying ConPTY handle is not documented thread-safe;
        # serialize writes so concurrent /term/write calls can't interleave.
        with self.write_lock:
            return self.pty.write(text)

    def drain(self, max_bytes):
        with self.buffer_lock:
            if max_bytes is None or max_bytes >= len(self.buffer):
                out = bytes(self.buffer)
                self.buffer.clear()
            else:
                # Return up to max_bytes without splitting a UTF-8 character.
                cut = _utf8_safe_cut(self.buffer, max_bytes)
                out = bytes(self.buffer[:cut])
                del self.buffer[:cut]
        return out

    def resize(self, cols, rows):
        try:
            self.pty.setwinsize(int(rows), int(cols))
            self.cols = int(cols)
            self.rows = int(rows)
        except Exception:
            pass

    def terminate(self):
        try:
            self.pty.terminate(force=True)
        except Exception:
            pass
        self.closed = True


def subprocess_join(parts):
    """Join a command list using shlex-style quoting for Windows shells."""
    quoted = []
    for p in parts:
        s = str(p)
        if not s or any(c in s for c in ' \t"'):
            quoted.append('"' + s.replace('"', '\\"') + '"')
        else:
            quoted.append(s)
    return " ".join(quoted)


def _resolve_default_command():
    return os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"


def _lookup(session_id):
    if not isinstance(session_id, str) or not session_id:
        return None
    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_id)


def _drop(session_id):
    with _SESSIONS_LOCK:
        return _SESSIONS.pop(session_id, None)


def register_routes(app, state, require_auth):

    @app.route("/term/start", methods=["POST"])
    @require_auth
    def route_term_start():
        if not _pty_available():
            return _windows_only(_PTY_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        with _SESSIONS_LOCK:
            # Evict sessions that already ended so they don't leak capacity.
            for sid in [sid for sid, s in _SESSIONS.items() if s is not None and s.closed]:
                _SESSIONS.pop(sid, None)
            if len(_SESSIONS) >= _MAX_SESSIONS:
                return jsonify({
                    "error": "session limit reached",
                    "max_sessions": _MAX_SESSIONS,
                }), 429

        raw_cmd = body.get("command") or body.get("cmd")
        if raw_cmd is None:
            command = _resolve_default_command()
        elif isinstance(raw_cmd, list):
            if not raw_cmd:
                return jsonify({"error": "command list is empty"}), 400
            for item in raw_cmd:
                if not isinstance(item, str):
                    return jsonify({"error": "command list entries must be strings"}), 400
            command = subprocess_join(raw_cmd)
        elif isinstance(raw_cmd, str):
            command = raw_cmd.strip()
            if not command:
                return jsonify({"error": "command is empty"}), 400
        else:
            return jsonify({"error": "command must be a string or list of strings"}), 400

        try:
            cols = int(body.get("cols") or _DEFAULT_COLS)
            rows = int(body.get("rows") or _DEFAULT_ROWS)
        except (TypeError, ValueError):
            return jsonify({"error": "cols/rows must be integers"}), 400
        cols = max(20, min(cols, 500))
        rows = max(5, min(rows, 200))

        cwd = body.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            return jsonify({"error": "cwd must be a string"}), 400
        if cwd:
            cwd = os.path.abspath(os.path.expanduser(cwd))
            if not os.path.isdir(cwd):
                return jsonify({"error": "cwd not found", "cwd": cwd}), 400

        env_override = body.get("env")
        env = None
        if isinstance(env_override, dict):
            env = os.environ.copy()
            for k, v in env_override.items():
                if isinstance(k, str) and isinstance(v, (str, int, float)):
                    env[k] = str(v)

        session_id = uuid.uuid4().hex
        with _SESSIONS_LOCK:
            # Reserve the slot now; re-check capacity under the same lock to
            # close the check-then-insert TOCTOU gap that could let concurrent
            # /term/start requests exceed _MAX_SESSIONS.
            if len(_SESSIONS) >= _MAX_SESSIONS:
                return jsonify({
                    "error": "session limit reached",
                    "max_sessions": _MAX_SESSIONS,
                }), 429
            _SESSIONS[session_id] = None

        try:
            session = _Session(session_id, command, cols, rows, cwd=cwd, env=env)
        except Exception as exc:
            with _SESSIONS_LOCK:
                _SESSIONS.pop(session_id, None)
            _log(f"term/start spawn failed: {exc}")
            return jsonify({"error": f"spawn failed: {exc}"}), 500

        with _SESSIONS_LOCK:
            _SESSIONS[session_id] = session

        _log(f"term/start id={session_id} pid={session.pid} cmd={command!r}")
        return jsonify({
            "session_id": session_id,
            "pid": session.pid,
            "cols": session.cols,
            "rows": session.rows,
            "command": command,
        })

    @app.route("/term/write", methods=["POST"])
    @require_auth
    def route_term_write():
        if not _pty_available():
            return _windows_only(_PTY_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        session_id = body.get("session_id") or body.get("id")
        if not session_id:
            return _missing_field("session_id")
        session = _lookup(session_id)
        if session is None:
            return jsonify({"error": "unknown session_id"}), 404

        data = body.get("data")
        if data is None:
            data = body.get("input")
        if data is None:
            return _missing_field("data")

        if isinstance(data, str):
            payload = data
        elif isinstance(data, (bytes, bytearray)):
            payload = bytes(data).decode("utf-8", errors="replace")
        else:
            return jsonify({"error": "data must be a string"}), 400

        # Optional convenience: append_newline appends "\r" (Enter key) so the
        # caller does not need to embed control chars in JSON.
        if bool(body.get("append_newline")):
            payload += "\r"

        if len(payload.encode("utf-8", errors="replace")) > _MAX_WRITE_BYTES:
            return jsonify({
                "error": "write too large",
                "max_bytes": _MAX_WRITE_BYTES,
            }), 413

        try:
            written = session.write(payload.encode("utf-8"))
        except OSError as exc:
            return jsonify({"error": f"write failed: {exc}", "closed": session.closed}), 500

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "written": int(written) if written is not None else len(payload),
            "closed": session.closed,
        })

    @app.route("/term/read", methods=["POST"])
    @require_auth
    def route_term_read():
        if not _pty_available():
            return _windows_only(_PTY_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        session_id = body.get("session_id") or body.get("id")
        if not session_id:
            return _missing_field("session_id")
        session = _lookup(session_id)
        if session is None:
            return jsonify({"error": "unknown session_id"}), 404

        try:
            max_bytes = int(body.get("max_bytes") or _MAX_READ_BYTES)
        except (TypeError, ValueError):
            max_bytes = _MAX_READ_BYTES
        max_bytes = max(1, min(max_bytes, _MAX_READ_BYTES))

        try:
            timeout = float(body.get("timeout") or 0.0)
        except (TypeError, ValueError):
            timeout = 0.0
        timeout = max(0.0, min(timeout, 30.0))

        # Optional short poll: wait up to `timeout` seconds for output to arrive
        # so /term/read can be used in a blocking style for interactive prompts.
        deadline = time.time() + timeout if timeout > 0 else 0.0
        while True:
            data = session.drain(max_bytes)
            if data or timeout <= 0.0 or time.time() >= deadline or session.closed:
                break
            time.sleep(0.05)

        text = data.decode("utf-8", errors="replace") if data else ""
        return jsonify({
            "session_id": session_id,
            "data": text,
            "bytes": len(data),
            "closed": session.closed,
            "exit_status": session.exit_status,
            "read_error": session.read_error,
        })

    @app.route("/term/close", methods=["POST"])
    @require_auth
    def route_term_close():
        if not _pty_available():
            return _windows_only(_PTY_IMPORT_ERROR)

        body = _json_body()
        if not isinstance(body, dict):
            body = {}

        session_id = body.get("session_id") or body.get("id")
        if not session_id:
            return _missing_field("session_id")

        session = _drop(session_id)
        if session is None:
            return jsonify({"error": "unknown session_id"}), 404

        session.terminate()
        _log(f"term/close id={session_id} exit={session.exit_status}")
        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "closed": True,
            "exit_status": session.exit_status,
        })
