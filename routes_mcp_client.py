"""MCP client routes for Hermes CoAgent.

Connects OUT to external Model Context Protocol servers over stdio or HTTP,
aggregates their tools under a unified namespace, and exposes endpoints to
register, list, call, and unregister them. Sibling to routes_mcp.py, which
exposes CoAgent's OWN endpoints AS an MCP server; this module is the client.
"""
import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from queue import Queue, Empty

from flask import jsonify, request

from shared import COAGENT_DIR, _log


PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "coagent-mcp-client", "version": "1.0.0"}
MAX_SERVERS = 32
DEFAULT_TIMEOUT = 30.0
INIT_TIMEOUT = 30.0
SHUTDOWN_TIMEOUT = 3.0
MAX_STDIO_LINE_BYTES = 8 * 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 16 * 1024 * 1024
NAME_REGEX = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,63}\Z")

# Environment variables that are safe to inherit into user-registered MCP
# server subprocesses. The parent CoAgent process may hold secrets (auth
# tokens, cloud/tunnel credentials, etc.); inheriting its full environment
# would hand those to any arbitrary command a caller registers. Callers pass
# additional variables explicitly via the `env` field.
_SAFE_INHERITED_ENV_KEYS = frozenset((
    "PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "HOMEDRIVE", "HOMEPATH", "OS", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "USERNAME", "USERDOMAIN",
    "ProgramFiles", "ProgramFiles(x86)", "CommonProgramFiles",
    "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "SSL_CERT_FILE",
))

SERVERS = {}
REGISTRY_LOCK = threading.RLock()


def _sanitize_error(msg, max_len=500):
    if msg is None:
        return ""
    try:
        s = str(msg)
    except Exception:
        s = "<unstringifiable error>"
    s = s.replace("\r", " ").replace("\n", " ").strip()
    if len(s) > max_len:
        s = s[:max_len] + "...(truncated)"
    return s


def _valid_name(name):
    return isinstance(name, str) and bool(NAME_REGEX.match(name))


class _HttpResp:
    """Minimal requests-like response returned by :func:`_http_post`."""

    def __init__(self, status_code, headers, text):
        self.status_code = status_code
        self.headers = headers
        self.text = text

    def json(self):
        return json.loads(self.text)


def _read_bounded(stream, cap):
    """Read a stream in chunks up to ``cap`` bytes. Raises MCPError past cap."""
    chunks = []
    total = 0
    while True:
        chunk = stream.read(min(65536, cap - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            raise MCPError(f"response exceeds {cap} byte limit", status=502)
    return b"".join(chunks)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Block HTTP redirects so a validated URL cannot 302 to an internal host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _resolve_host(host, port):
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    addrs = []
    for info in infos:
        try:
            addrs.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return addrs


def _url_is_unsafe(url):
    """Return True if a URL resolves to a loopback/private/link-local/metadata host.

    The HTTP MCP transport lets callers point the client at arbitrary
    endpoints; without this guard an authenticated caller could SSRF internal
    services and cloud metadata endpoints (169.254.169.254, fd00:ec2::254, etc.).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return True
    if parsed.scheme.lower() not in ("http", "https"):
        return True
    host = parsed.hostname
    if not host:
        return True
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    addrs = _resolve_host(host, port)
    if not addrs:
        # Fail closed: if the host can't be resolved here we can't validate it,
        # and attacker-controlled DNS can return a different answer at connect
        # time (DNS rebinding).
        return True
    for ip in addrs:
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) so the
        # loopback/private/link-local checks actually apply.
        if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
            ip = ip.ipv4_mapped
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return True
    return False


def _http_post(url, data_bytes, headers, timeout):
    """POST bytes to ``url`` using stdlib urllib (no third-party dependency).

    Returns an :class:`_HttpResp`. Raises :class:`MCPError` on network errors.
    HTTP error statuses (4xx/5xx) are NOT raised here — the caller inspects
    ``status_code`` so it can surface the server's error body.
    """
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
            body = _read_bounded(resp, MAX_HTTP_RESPONSE_BYTES).decode("utf-8", errors="replace")
            return _HttpResp(resp.status, dict(resp.headers.items()), body)
    except MCPError:
        raise
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_HTTP_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
            if len(body) > MAX_HTTP_RESPONSE_BYTES:
                body = body[:MAX_HTTP_RESPONSE_BYTES]
        except Exception:
            body = ""
        headers = dict(e.headers.items()) if e.headers else {}
        return _HttpResp(e.code, headers, body)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        text = str(reason)
        if isinstance(reason, TimeoutError) or "timed out" in text.lower() or "timeout" in text.lower():
            raise MCPError(f"http timeout: {_sanitize_error(reason)}", status=504)
        raise MCPError(f"http request failed: {_sanitize_error(reason)}", status=502)
    except TimeoutError as e:
        raise MCPError(f"http timeout: {_sanitize_error(e)}", status=504)


class MCPError(Exception):
    def __init__(self, message, status=400, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class StdioServer:
    def __init__(self, name, command, args=None, env=None):
        self.name = name
        self.transport = "stdio"
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.proc = None
        self.lock = threading.Lock()
        self.reader_thread = None
        self.stderr_thread = None
        self.stopped = threading.Event()
        self.response_queues = {}
        self.response_queues_lock = threading.Lock()
        self.next_id = 1
        self.tools = []
        self.server_info = {}
        self.stderr_buf = []
        self.stderr_buf_lock = threading.Lock()
        self.created_at = time.time()

    def status(self):
        if self.proc is None:
            return "not_started"
        rc = self.proc.poll()
        if rc is not None:
            return f"exited({rc})"
        return "running"

    def _build_argv(self):
        if isinstance(self.command, list):
            argv = list(self.command) + list(self.args)
        elif isinstance(self.command, str):
            if self.args:
                argv = [self.command] + list(self.args)
            else:
                argv = shlex.split(self.command, posix=(os.name != "nt"))
        else:
            raise MCPError("command must be string or list", status=400)
        if not argv:
            raise MCPError("empty command", status=400)
        return argv

    def start(self):
        argv = self._build_argv()
        proc_env = {k: v for k, v in os.environ.items()
                    if k in _SAFE_INHERITED_ENV_KEYS}
        for k, v in self.env.items():
            if not isinstance(k, str):
                continue
            proc_env[k] = str(v)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                bufsize=0,
                cwd=str(COAGENT_DIR) if COAGENT_DIR else None,
                creationflags=creationflags,
            )
        except FileNotFoundError:
            raise MCPError(f"command not found: {argv[0]}", status=400)
        except OSError as e:
            raise MCPError(f"failed to spawn process: {_sanitize_error(e)}", status=400)

        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"mcp-stdio-{self.name}-reader",
            daemon=True,
        )
        self.reader_thread.start()
        self.stderr_thread = threading.Thread(
            target=self._stderr_loop,
            name=f"mcp-stdio-{self.name}-stderr",
            daemon=True,
        )
        self.stderr_thread.start()

    def _reader_loop(self):
        try:
            while not self.stopped.is_set():
                line = self.proc.stdout.readline(MAX_STDIO_LINE_BYTES)
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    _log(f"[mcp-client:{self.name}] non-JSON stdout: {text[:200]}")
                    continue
                if not isinstance(msg, dict):
                    continue
                msg_id = msg.get("id")
                if msg_id is None:
                    continue
                with self.response_queues_lock:
                    q = self.response_queues.get(msg_id)
                if q is not None:
                    q.put(msg)
        except Exception as e:
            _log(f"[mcp-client:{self.name}] reader error: {_sanitize_error(e)}")
        finally:
            self.stopped.set()
            with self.response_queues_lock:
                for q in self.response_queues.values():
                    try:
                        q.put({"id": None, "error": {"message": "connection closed"}})
                    except Exception:
                        pass

    def _stderr_loop(self):
        try:
            while not self.stopped.is_set():
                line = self.proc.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                with self.stderr_buf_lock:
                    self.stderr_buf.append(text)
                    if len(self.stderr_buf) > 200:
                        self.stderr_buf = self.stderr_buf[-200:]
        except Exception:
            pass

    def _write_message(self, msg):
        data = (json.dumps(msg) + "\n").encode("utf-8")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPError(f"stdio write failed: {_sanitize_error(e)}", status=502)

    def _next_id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def request(self, method, params=None, timeout=DEFAULT_TIMEOUT):
        # Serialize only id allocation + write; the per-id response queue makes
        # the wait thread-safe without holding self.lock (which would serialize
        # ALL requests to this server behind one slow call).
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                raise MCPError(f"server '{self.name}' not running", status=502)
            req_id = self._next_id()
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                msg["params"] = params
            q = Queue()
            with self.response_queues_lock:
                self.response_queues[req_id] = q
            try:
                self._write_message(msg)
            except Exception:
                with self.response_queues_lock:
                    self.response_queues.pop(req_id, None)
                raise
            # Re-check: the reader may have already hit EOF and stopped before
            # we registered our queue, in which case we'd hang until timeout.
            if self.stopped.is_set():
                with self.response_queues_lock:
                    self.response_queues.pop(req_id, None)
                raise MCPError("stdio connection lost", status=502)

        # Wait OUTSIDE the write lock so concurrent calls can proceed.
        try:
            resp = q.get(timeout=timeout)
        except Empty:
            raise MCPError(
                f"timeout waiting for response to '{method}'",
                status=504,
            )
        finally:
            with self.response_queues_lock:
                self.response_queues.pop(req_id, None)

        if "error" in resp and resp.get("id") is None:
            raise MCPError("stdio connection lost", status=502)
        if "error" in resp:
            err = resp["error"] or {}
            raise MCPError(
                f"jsonrpc error: {_sanitize_error(err.get('message'))}",
                status=502,
                detail=err,
            )
        return resp.get("result", {})

    def notify(self, method, params=None):
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                raise MCPError(f"server '{self.name}' not running", status=502)
            msg = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                msg["params"] = params
            self._write_message(msg)

    def stderr_tail(self, n=50):
        with self.stderr_buf_lock:
            return list(self.stderr_buf[-n:])

    def shutdown(self):
        self.stopped.set()
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=SHUTDOWN_TIMEOUT)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        finally:
            for stream_name in ("stdin", "stdout", "stderr"):
                s = getattr(proc, stream_name, None)
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass


class HttpServer:
    def __init__(self, name, url, headers=None):
        self.name = name
        self.transport = "http"
        self.url = url
        self.headers = dict(headers or {})
        self.lock = threading.Lock()
        self.next_id = 1
        self.tools = []
        self.server_info = {}
        self.session_id = None
        self.created_at = time.time()
        self.alive = True

    def status(self):
        return "running" if self.alive else "closed"

    def start(self):
        pass

    def _default_headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"coagent-mcp-client/{CLIENT_INFO['version']}",
        }
        for k, v in self.headers.items():
            if not isinstance(k, str):
                continue
            h[k] = str(v)
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _parse_sse(self, text):
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        return None

    def _next_id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def _post(self, payload, timeout, expect_response):
        resp = _http_post(
            self.url,
            json.dumps(payload).encode("utf-8"),
            self._default_headers(),
            timeout,
        )

        sid = next(
            (v for k, v in resp.headers.items() if k.lower() == "mcp-session-id"),
            None,
        )
        if sid and 200 <= resp.status_code < 300:
            self.session_id = sid

        if resp.status_code == 202 and not expect_response:
            return None

        if resp.status_code >= 400:
            raise MCPError(
                f"http {resp.status_code}: {_sanitize_error((resp.text or '')[:400])}",
                status=502,
            )

        if not expect_response:
            return None

        ctype = (resp.headers.get("Content-Type") or "").lower()
        text = resp.text or ""
        if "text/event-stream" in ctype:
            data = self._parse_sse(text)
            if data is None:
                raise MCPError("empty SSE response", status=502)
            return data
        try:
            return resp.json()
        except ValueError:
            data = self._parse_sse(text)
            if data is not None:
                return data
            raise MCPError(
                f"invalid JSON response: {_sanitize_error(text[:200])}",
                status=502,
            )

    def request(self, method, params=None, timeout=DEFAULT_TIMEOUT):
        with self.lock:
            if not self.alive:
                raise MCPError(f"server '{self.name}' is closed", status=502)
            req_id = self._next_id()
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
        # HTTP call outside the lock so one slow tool call doesn't serialize
        # every other request to this server.
        resp = self._post(payload, timeout, expect_response=True)
        if resp is None:
            raise MCPError("no response body from server", status=502)
        if not isinstance(resp, dict):
            raise MCPError("unexpected non-object jsonrpc response", status=502)
        if "error" in resp:
            err = resp["error"] or {}
            raise MCPError(
                f"jsonrpc error: {_sanitize_error(err.get('message'))}",
                status=502,
                detail=err,
            )
        return resp.get("result", {})

    def notify(self, method, params=None):
        with self.lock:
            if not self.alive:
                raise MCPError(f"server '{self.name}' is closed", status=502)
            payload = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                payload["params"] = params
            try:
                self._post(payload, timeout=10.0, expect_response=False)
            except MCPError:
                pass

    def stderr_tail(self, n=50):
        return []

    def shutdown(self):
        if not self.alive:
            return
        self.alive = False
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"reason": "client unregister"},
            }
            _http_post(
                self.url,
                json.dumps(payload).encode("utf-8"),
                self._default_headers(),
                3.0,
            )
        except Exception:
            pass


def _handshake(server):
    init_params = {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": CLIENT_INFO,
    }
    result = server.request("initialize", init_params, timeout=INIT_TIMEOUT)
    if not isinstance(result, dict):
        raise MCPError("invalid initialize result", status=502)
    server.server_info = {
        "protocolVersion": result.get("protocolVersion"),
        "serverInfo": result.get("serverInfo", {}),
        "capabilities": result.get("capabilities", {}),
    }
    try:
        server.notify("notifications/initialized")
    except MCPError as e:
        raise MCPError(f"initialized notification failed: {_sanitize_error(e)}", status=502)

    caps = server.server_info.get("capabilities") or {}
    if isinstance(caps, dict) and caps.get("tools") is None and caps:
        server.tools = []
        return
    try:
        tools_result = server.request("tools/list", timeout=INIT_TIMEOUT)
        raw_tools = tools_result.get("tools", []) if isinstance(tools_result, dict) else []
        server.tools = [t for t in (raw_tools or []) if isinstance(t, dict)]
    except MCPError as e:
        _log(f"[mcp-client:{server.name}] tools/list failed: {_sanitize_error(e)}")
        server.tools = []


def _register_stdio(name, command, args, env):
    if command is None or (isinstance(command, str) and not command.strip()):
        raise MCPError("stdio transport requires 'command'", status=400)
    if not isinstance(args, list):
        raise MCPError("'args' must be a list", status=400)
    if not isinstance(env, dict):
        raise MCPError("'env' must be an object", status=400)
    server = StdioServer(name=name, command=command, args=args, env=env)
    try:
        server.start()
        _handshake(server)
    except MCPError:
        try:
            server.shutdown()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            server.shutdown()
        except Exception:
            pass
        raise MCPError(f"initialize failed: {_sanitize_error(e)}", status=400)
    return server


def _register_http(name, url, headers):
    if not isinstance(url, str) or not url:
        raise MCPError("http transport requires 'url'", status=400)
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        raise MCPError("invalid url", status=400)
    if parsed.scheme.lower() not in ("http", "https"):
        raise MCPError("url must be http:// or https://", status=400)
    if _url_is_unsafe(url):
        raise MCPError("url resolves to a loopback/private/link-local address (SSRF blocked)", status=400)
    if not isinstance(headers, dict):
        raise MCPError("'headers' must be an object", status=400)
    server = HttpServer(name=name, url=url, headers=headers)
    try:
        server.start()
        _handshake(server)
    except MCPError:
        try:
            server.shutdown()
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            server.shutdown()
        except Exception:
            pass
        raise MCPError(f"initialize failed: {_sanitize_error(e)}", status=400)
    return server


def _tool_summary(server):
    out = []
    for t in server.tools:
        if not isinstance(t, dict):
            continue
        out.append({
            "name": t.get("name"),
            "server": server.name,
            "description": t.get("description", "") or "",
            "input_schema": t.get("inputSchema") or t.get("input_schema") or {},
        })
    return out


def _server_summary(server):
    return {
        "name": server.name,
        "transport": server.transport,
        "status": server.status(),
        "tool_count": len(server.tools),
        "server_info": (server.server_info or {}).get("serverInfo", {}),
        "protocol_version": (server.server_info or {}).get("protocolVersion"),
        "created_at": server.created_at,
    }


def _all_tools():
    with REGISTRY_LOCK:
        servers = list(SERVERS.values())
    out = []
    for s in servers:
        out.extend(_tool_summary(s))
    return out


def _all_servers():
    with REGISTRY_LOCK:
        servers = list(SERVERS.values())
    return [_server_summary(s) for s in servers]


def register_routes(app, state, require_auth):
    @app.route("/mcp/client/register", methods=["POST"])
    @require_auth
    def mcp_client_register():
        body = request.get_json(force=True, silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400

        name = body.get("name")
        transport = (body.get("transport") or "").strip().lower() if isinstance(body.get("transport"), str) else ""
        if not _valid_name(name):
            return jsonify({
                "ok": False,
                "error": "invalid 'name' (must match ^[A-Za-z_][A-Za-z0-9_.-]{0,63}$)",
            }), 400
        if transport not in ("stdio", "http"):
            return jsonify({"ok": False, "error": "transport must be 'stdio' or 'http'"}), 400

        with REGISTRY_LOCK:
            if name in SERVERS:
                return jsonify({"ok": False, "error": f"server '{name}' already registered"}), 409
            if len(SERVERS) >= MAX_SERVERS:
                return jsonify({
                    "ok": False,
                    "error": f"server registry full (max {MAX_SERVERS})",
                }), 429

        try:
            if transport == "stdio":
                server = _register_stdio(
                    name=name,
                    command=body.get("command"),
                    args=body.get("args", []),
                    env=body.get("env", {}),
                )
            else:
                server = _register_http(
                    name=name,
                    url=body.get("url"),
                    headers=body.get("headers", {}),
                )
        except MCPError as e:
            _log(f"[mcp-client] register '{name}' failed: {_sanitize_error(e)}")
            return jsonify({
                "ok": False,
                "error": _sanitize_error(e),
                "detail": e.detail if isinstance(e.detail, (dict, list, str, int, float, bool)) else None,
            }), e.status
        except Exception as e:
            _log(f"[mcp-client] register '{name}' unexpected: {_sanitize_error(e)}")
            return jsonify({"ok": False, "error": _sanitize_error(e)}), 500

        with REGISTRY_LOCK:
            if name in SERVERS:
                try:
                    server.shutdown()
                except Exception:
                    pass
                return jsonify({
                    "ok": False,
                    "error": f"server '{name}' registered concurrently",
                }), 409
            if len(SERVERS) >= MAX_SERVERS:
                try:
                    server.shutdown()
                except Exception:
                    pass
                return jsonify({
                    "ok": False,
                    "error": f"server registry full (max {MAX_SERVERS})",
                }), 429
            SERVERS[name] = server

        _log(f"[mcp-client] registered '{name}' ({transport}) with {len(server.tools)} tools")
        return jsonify({
            "ok": True,
            "server": _server_summary(server),
            "tools": _tool_summary(server),
        })

    @app.route("/mcp/client/servers", methods=["GET"])
    @require_auth
    def mcp_client_servers():
        return jsonify({
            "ok": True,
            "count": len(SERVERS),
            "servers": _all_servers(),
        })

    @app.route("/mcp/client/tools", methods=["GET"])
    @require_auth
    def mcp_client_tools():
        server_filter = request.args.get("server")
        with REGISTRY_LOCK:
            if server_filter:
                s = SERVERS.get(server_filter)
                if s is None:
                    return jsonify({
                        "ok": False,
                        "error": f"unknown server '{server_filter}'",
                    }), 404
                tools = _tool_summary(s)
            else:
                tools = []
                for s in SERVERS.values():
                    tools.extend(_tool_summary(s))
        return jsonify({"ok": True, "count": len(tools), "tools": tools})

    @app.route("/mcp/client/call", methods=["POST"])
    @require_auth
    def mcp_client_call():
        body = request.get_json(force=True, silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400

        server_name = body.get("server")
        tool_name = body.get("tool")
        arguments = body.get("arguments")
        if arguments is None:
            arguments = {}

        if not isinstance(server_name, str) or not server_name:
            return jsonify({"ok": False, "error": "missing 'server'"}), 400
        if not isinstance(tool_name, str) or not tool_name:
            return jsonify({"ok": False, "error": "missing 'tool'"}), 400
        if not isinstance(arguments, dict):
            return jsonify({"ok": False, "error": "'arguments' must be an object"}), 400

        with REGISTRY_LOCK:
            server = SERVERS.get(server_name)
        if server is None:
            return jsonify({"ok": False, "error": f"unknown server '{server_name}'"}), 404

        tool_names = {t.get("name") for t in server.tools if isinstance(t, dict)}
        if tool_name not in tool_names:
            return jsonify({
                "ok": False,
                "error": f"unknown tool '{tool_name}' on server '{server_name}'",
                "available": sorted(n for n in tool_names if isinstance(n, str)),
            }), 404

        timeout = DEFAULT_TIMEOUT
        raw_to = body.get("timeout")
        if raw_to is not None:
            try:
                t = float(raw_to)
                if 1.0 <= t <= 300.0:
                    timeout = t
            except (TypeError, ValueError):
                pass

        try:
            result = server.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=timeout,
            )
        except MCPError as e:
            _log(f"[mcp-client] call '{server_name}.{tool_name}' failed: {_sanitize_error(e)}")
            return jsonify({
                "ok": False,
                "error": _sanitize_error(e),
                "detail": e.detail if isinstance(e.detail, (dict, list, str, int, float, bool)) else None,
            }), e.status
        except Exception as e:
            _log(f"[mcp-client] call '{server_name}.{tool_name}' unexpected: {_sanitize_error(e)}")
            return jsonify({"ok": False, "error": _sanitize_error(e)}), 500

        content = []
        is_error = False
        if isinstance(result, dict):
            raw_content = result.get("content")
            if isinstance(raw_content, list):
                content = raw_content
            is_error = bool(result.get("isError"))

        return jsonify({
            "ok": not is_error,
            "server": server_name,
            "tool": tool_name,
            "content": content,
            "is_error": is_error,
            "raw": result if isinstance(result, (dict, list, str, int, float, bool)) or result is None else None,
        })

    @app.route("/mcp/client/unregister", methods=["POST"])
    @require_auth
    def mcp_client_unregister():
        body = request.get_json(force=True, silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "body must be a JSON object"}), 400

        name = body.get("name")
        if not _valid_name(name):
            return jsonify({"ok": False, "error": "invalid 'name'"}), 400

        with REGISTRY_LOCK:
            server = SERVERS.pop(name, None)
        if server is None:
            return jsonify({"ok": False, "error": f"unknown server '{name}'"}), 404

        try:
            server.shutdown()
        except Exception as e:
            _log(f"[mcp-client] shutdown '{name}' warning: {_sanitize_error(e)}")

        _log(f"[mcp-client] unregistered '{name}'")
        return jsonify({"ok": True, "name": name})

    @app.route("/mcp/client/logs", methods=["GET"])
    @require_auth
    def mcp_client_logs():
        name = request.args.get("server")
        if not name or not _valid_name(name):
            return jsonify({"ok": False, "error": "missing or invalid 'server'"}), 400
        with REGISTRY_LOCK:
            server = SERVERS.get(name)
        if server is None:
            return jsonify({"ok": False, "error": f"unknown server '{name}'"}), 404
        return jsonify({
            "ok": True,
            "server": name,
            "status": server.status(),
            "stderr_tail": server.stderr_tail(50),
        })

    try:
        state.mcp_client = {
            "servers": lambda: _all_servers(),
            "tools": lambda: _all_tools(),
        }
    except Exception as e:
        _log(f"[mcp-client] failed to attach state.mcp_client: {_sanitize_error(e)}")
