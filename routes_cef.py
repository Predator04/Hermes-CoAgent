"""CEF (Chromium Embedded Framework) automation via Chrome DevTools Protocol.

CEF apps (NVIDIA App, Spotify, Discord, Steam, etc.) render web content that
UIA cannot see. This module finds the CDP debug port exposed by CEF processes,
connects over WebSocket, and provides DOM inspection and input injection.
"""

import json
import socket
import threading
import time
import urllib.request
import urllib.error

from flask import jsonify, request
from shared import _json_body, _log

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_sessions: dict = {}   # port -> {"ws": _CDPSocket, "pages": list, "page_id": str}
_sessions_lock = threading.Lock()

_passive_scan_cache: dict = {"ts": 0.0, "result": []}
_cef_cache: dict = {"ts": 0.0, "data": {}}

# Ports to probe when process command-line inspection yields nothing.
_FALLBACK_PORTS = [9222, 9229, 9223, 9224, 9225]

# Known CEF-hosting app executables (matched case-insensitively as a substring
# of the process name).  NVIDIA App, Spotify, Discord, VS Code, Slack, Teams,
# Steam's overlay browser, and the Edge WebView2 runtime all embed CEF/Chromium.
_CEF_HOST_NAMES = (
    "nvidia app",
    "nvidia broadcast",
    "nvidia overlay",
    "spotify",
    "discord",
    "slack",
    "teams",
    "steamwebhelper",
    "msedgewebview2",
    "cefsharp",
    "electron",
    "notion",
    "figma",
    "obsidian",
    "1password",
    # VS Code — process name has no ".exe" suffix when read via Get-Process
    "code",
)

# CEF / Chromium runtime DLLs.  Presence in a process' loaded modules is strong
# evidence the process hosts a Chromium renderer.
_CEF_DLLS = (
    "libcef.dll",
    "cef.dll",
    "chrome_elf.dll",
    "nw_elf.dll",
    "libcef_dll_wrapper.dll",
    # chrome.dll is more ambiguous (Chrome itself), but still a valid signal
    "chrome.dll",
)

# Strong cmdline markers: these flags are only ever passed to Chromium child
# workers (renderer/gpu/utility) or to processes explicitly launched with a
# custom user-data dir or subprocess path.
_CEF_CMDLINE_STRONG = (
    "--type=renderer",
    "--type=gpu-process",
    "--type=utility",
    "--type=crashpad-handler",
    "--browser-subprocess-path=",
)

# Weaker signal: many non-CEF Chromium-derived processes also carry these, but
# combined with a name or DLL hit they confirm CEF hosting.
_CEF_CMDLINE_WEAK = (
    "--user-data-dir=",
    "--field-trial-handle=",
)


# ---------------------------------------------------------------------------
# Minimal synchronous CDP WebSocket client (no external deps)
# ---------------------------------------------------------------------------

class _CDPSocket:
    """Bare-minimum synchronous WebSocket client for CDP frames."""

    def __init__(self, host: str, port: int, path: str, timeout: float = 10.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buf = b""
        self._cmd_id = 0
        self._lock = threading.Lock()
        self._pending: dict = {}   # id -> threading.Event + result slot
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._running = True
        try:
            self._do_handshake(host, port, path)
            self._reader.start()
        except Exception:
            self._running = False
            try:
                self._sock.close()
            except Exception:
                pass
            raise

    # ------------------------------------------------------------------
    # WebSocket handshake (RFC 6455)
    # ------------------------------------------------------------------

    def _do_handshake(self, host: str, port: int, path: str) -> None:
        import base64, os
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(handshake.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed — connection closed")
            resp += chunk
        if b"101" not in resp:
            raise ConnectionError(f"WebSocket upgrade rejected: {resp[:200]!r}")

    # ------------------------------------------------------------------
    # Frame encode / decode (text frames, no masking on server→client)
    # ------------------------------------------------------------------

    def _encode_frame(self, payload: bytes) -> bytes:
        import os
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length < 126:
            header = bytes([0x81, 0x80 | length]) + mask
        elif length < 65536:
            header = bytes([0x81, 0xFE]) + length.to_bytes(2, "big") + mask
        else:
            header = bytes([0x81, 0xFF]) + length.to_bytes(8, "big") + mask
        return header + masked

    def _recv_frame(self) -> str | None:
        """Read one complete WebSocket frame from the socket.

        Returns the decoded text payload for data frames, or None for control
        frames that were handled internally (ping→pong, pong).  Raises
        ConnectionError on close frames or a broken connection.
        """
        import os as _os

        def recv_exact(n):
            buf = b""
            while len(buf) < n:
                chunk = self._sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("CDP connection closed")
                buf += chunk
            return buf

        header = recv_exact(2)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(recv_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(recv_exact(8), "big")
        mask_bytes = recv_exact(4) if masked else b""
        payload = recv_exact(length)
        if masked:
            payload = bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(payload))

        if opcode == 0x8:   # Close frame
            raise ConnectionError("CDP sent WebSocket close frame")
        if opcode == 0x9:   # Ping — reply with Pong (opcode 0xA, mask required)
            mask = _os.urandom(4)
            masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            pong_len = len(payload)
            pong_header = bytes([0x8A, 0x80 | pong_len]) + mask
            try:
                self._sock.sendall(pong_header + masked_payload)
            except Exception:
                pass
            return None
        if opcode == 0xA:   # Pong — ignore
            return None

        return payload.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Background reader — dispatches responses to waiting callers
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        while self._running:
            try:
                text = self._recv_frame()
                if text is None:
                    continue   # control frame handled internally (ping/pong)
                msg = json.loads(text)
                cmd_id = msg.get("id")
                if cmd_id is not None:
                    with self._lock:
                        slot = self._pending.get(cmd_id)
                    if slot:
                        slot["result"] = msg
                        slot["event"].set()
            except Exception as exc:
                self._running = False
                # Connection lost — wake every in-flight caller immediately so
                # they raise ConnectionError instead of blocking to timeout.
                with self._lock:
                    for slot in self._pending.values():
                        slot["error"] = exc
                        slot["event"].set()
                    self._pending.clear()
                break

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        """Send a CDP command and return the response (blocks until reply)."""
        if not self._running:
            raise ConnectionError("CDP connection is closed")

        with self._lock:
            self._cmd_id += 1
            cmd_id = self._cmd_id
            ev = threading.Event()
            self._pending[cmd_id] = {"event": ev, "result": None}

        payload = json.dumps({"id": cmd_id, "method": method, "params": params or {}}).encode()
        try:
            self._sock.sendall(self._encode_frame(payload))
        except Exception:
            with self._lock:
                self._pending.pop(cmd_id, None)
            raise

        triggered = ev.wait(timeout)

        with self._lock:
            slot = self._pending.pop(cmd_id, {})

        if slot.get("error") is not None:
            raise ConnectionError(
                f"CDP connection lost while awaiting '{method}': {slot['error']}"
            )
        if not triggered:
            raise TimeoutError(f"CDP command '{method}' timed out after {timeout}s")
        return slot.get("result", {})

    def close(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _http_get_json(url: str, timeout: float = 3.0):
    """Fetch JSON from a plain HTTP URL (used for /json endpoint)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        raise ConnectionError(f"Cannot reach {url}: {exc}") from exc


def _list_pages(port: int) -> list:
    """Return CDP page descriptors from http://127.0.0.1:{port}/json."""
    return _http_get_json(f"http://127.0.0.1:{port}/json")


def _pick_page(pages: list, title_hint: str | None = None) -> dict | None:
    """Select the best page from a CDP /json listing.

    Preference order:
    1. page whose title contains ``title_hint`` (case-insensitive)
    2. first page with type == "page"
    3. first entry overall
    """
    if not pages:
        return None
    if title_hint:
        hint = title_hint.lower()
        for p in pages:
            if hint in p.get("title", "").lower():
                return p
    for p in pages:
        if p.get("type") == "page":
            return p
    return pages[0]


def _connect_to_port(port: int, title_hint: str | None = None) -> tuple[_CDPSocket, list, str]:
    """Open a CDP WebSocket connection to ``port``.

    Returns ``(socket, pages, page_id)``.
    """
    from urllib.parse import urlparse
    pages = _list_pages(port)
    # Only targets with a debuggable WebSocket endpoint can be connected to —
    # service workers, DevTools frontends, and already-attached targets omit it.
    pages = [p for p in pages if p.get("webSocketDebuggerUrl")]
    page = _pick_page(pages, title_hint)
    if not page:
        raise ValueError(f"No debuggable pages found on port {port}")
    ws_url: str = page["webSocketDebuggerUrl"]
    # Parse path robustly — CEF may advertise localhost or 127.0.0.1
    parsed = urlparse(ws_url)
    path = parsed.path
    if not path:
        raise ValueError(f"Could not parse WebSocket path from URL: {ws_url!r}")
    ws = _CDPSocket("127.0.0.1", port, path)
    page_id: str = page.get("id", "")
    return ws, pages, page_id


def _get_session(port: int) -> dict:
    if isinstance(port, str):
        try:
            port = int(port)
        except ValueError:
            pass
    with _sessions_lock:
        sess = _sessions.get(port)
    if not sess:
        raise ValueError(f"No active CEF session on port {port}. Call /cef/connect first.")
    return sess


def _cdp(port: int, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    sess = _get_session(port)
    return sess["ws"].send(method, params, timeout)


# ---------------------------------------------------------------------------
# Process scanning (Windows — uses psutil which is already a dependency)
# ---------------------------------------------------------------------------

def _window_title_for_pid(pid: int) -> str:
    """Return the first visible top-level window title owned by ``pid``, or ""."""
    try:
        import ctypes
        titles: list = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)
        def _enum(hwnd, _lParam):
            win_pid = ctypes.c_ulong(0)
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
            if win_pid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value:
                    titles.append(buf.value)
            return True

        ctypes.windll.user32.EnumWindows(_enum, 0)
        return titles[0] if titles else ""
    except Exception:
        return ""


def _detect_cef_methods(proc, info: dict, check_dlls: bool = True) -> list[str]:
    """Return the list of detection methods that identify ``proc`` as CEF-hosting.

    Methods (in evidence order): "cmdline", "name", "dll", "cmdline-weak".
    Empty list means the process is not identified as CEF.  ``check_dlls=False``
    skips the memory_maps() probe (which is slow and often triggers AccessDenied).
    """
    import psutil

    methods: list[str] = []
    name = (info.get("name") or "").lower()
    cmdline_str = " ".join(info.get("cmdline") or [])

    if any(marker in cmdline_str for marker in _CEF_CMDLINE_STRONG):
        methods.append("cmdline")

    if any(host in name for host in _CEF_HOST_NAMES):
        methods.append("name")

    if check_dlls and not methods:
        try:
            for mmap in proc.memory_maps():
                mpath = (getattr(mmap, "path", "") or "").lower()
                if any(dll in mpath for dll in _CEF_DLLS):
                    methods.append("dll")
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied,
                AttributeError, NotImplementedError, OSError):
            pass

    if not methods and any(marker in cmdline_str for marker in _CEF_CMDLINE_WEAK):
        methods.append("cmdline-weak")

    return methods


def _scan_cef_processes() -> list[dict]:
    """Scan running processes for those advertising a CDP debug port."""
    import subprocess
    results = []
    try:
        ps_out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like '*--remote-debugging-port=*'} | "
             "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=8
        )
        if ps_out.returncode == 0 and ps_out.stdout:
            procs = json.loads(ps_out.stdout)
            if isinstance(procs, dict):
                procs = [procs]
            for p in procs:
                cmd = p.get("CommandLine", "")
                # Extract port
                port = None
                for part in cmd.split():
                    if part.startswith("--remote-debugging-port="):
                        try:
                            port = int(part.split("=", 1)[1])
                        except ValueError:
                            pass
                        break
                if not port:
                    continue
                pid = p.get("ProcessId", 0)
                results.append({
                    "pid": pid,
                    "name": p.get("Name", ""),
                    "window_title": "",
                    "debug_port": port,
                    "debug_url": f"http://127.0.0.1:{port}/json",
                })
    except Exception:
        pass
    return results


def _probe_fallback_ports() -> list[dict]:
    """Try connecting to common CDP ports when process scan yields nothing."""
    found = []
    for port in _FALLBACK_PORTS:
        try:
            pages = _list_pages(port)
            if pages:
                found.append({
                    "pid": None,
                    "name": "unknown",
                    "window_title": pages[0].get("title", ""),
                    "debug_port": port,
                    "debug_url": f"http://127.0.0.1:{port}/json",
                })
        except Exception:
            continue
    return found


def _scan_passive_cef_processes(include_titles: bool = False, fresh: bool = False) -> list[dict]:
    """Find running CEF apps that do NOT expose a CDP debug port.

    Two-pass PowerShell scan:
      Pass 1: Get-Process (name+PID) filtered by _CEF_HOST_NAMES. < 2s.
      Pass 2: WMI Win32_Process cmdline scan for unmatched PIDs. < 3s.

    Results cached for 30s. Pass fresh=True to bypass.
    No threading — pure synchronous subprocess calls; returns [] on failure.
    """
    import subprocess

    now = time.monotonic()
    if not fresh and now - _passive_scan_cache["ts"] < 30.0:
        return _passive_scan_cache["result"]

    apps: dict = {}  # pid -> entry

    def _record(pid: int, name: str, methods: list[str], child_pid: int | None) -> None:
        entry = apps.get(pid)
        if entry is None:
            entry = {
                "pid": pid,
                "name": name,
                "window_title": "",
                "detection_methods": [],
                "child_pids": [],
                "cdp_access": False,
            }
            apps[pid] = entry
        for m in methods:
            if m not in entry["detection_methods"]:
                entry["detection_methods"].append(m)
        if child_pid is not None and child_pid != pid and child_pid not in entry["child_pids"]:
            entry["child_pids"].append(child_pid)

    def _run_ps(command: str) -> list | None:
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return None
            data = json.loads(proc.stdout)
            return [data] if isinstance(data, dict) else data
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Pass 1: name-only via Get-Process — typically < 1s
    # ------------------------------------------------------------------
    name_matched_pids: set = set()
    procs = _run_ps("Get-Process | Select-Object Id,ProcessName | ConvertTo-Json -Compress")
    if procs:
        for p in procs:
            try:
                pid = int(p.get("Id") or 0)
                name = (p.get("ProcessName") or "").lower()
                if pid and any(host in name for host in _CEF_HOST_NAMES):
                    name_matched_pids.add(pid)
                    _record(pid, p.get("ProcessName") or "", ["name"], None)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Pass 2: WMI cmdline scan — skip PIDs already matched
    # ------------------------------------------------------------------
    wmi_procs = _run_ps(
        "Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -ne $null} | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    if wmi_procs:
        for p in wmi_procs:
            try:
                pid = int(p.get("ProcessId") or 0)
                if not pid or pid in name_matched_pids:
                    continue
                cmdline_str = p.get("CommandLine") or ""
                if "--remote-debugging-port=" in cmdline_str:
                    continue
                methods: list[str] = []
                if any(marker in cmdline_str for marker in _CEF_CMDLINE_STRONG):
                    methods.append("cmdline")
                if not methods and any(marker in cmdline_str for marker in _CEF_CMDLINE_WEAK):
                    methods.append("cmdline-weak")
                if not methods:
                    continue
                ppid = int(p.get("ParentProcessId") or 0)
                proc_name = p.get("Name") or ""
                worker_only = all(m.startswith("cmdline") for m in methods)
                if worker_only and ppid and ppid in apps:
                    _record(ppid, apps[ppid]["name"], methods, pid)
                else:
                    _record(pid, proc_name, methods, None)
            except Exception:
                continue

    results = list(apps.values())
    _passive_scan_cache["ts"] = time.monotonic()
    _passive_scan_cache["result"] = results
    return results


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app, state, require_auth):

    # -----------------------------------------------------------------------
    # Detection
    # -----------------------------------------------------------------------

    @app.route("/cef/detect", methods=["POST"])
    @require_auth
    def cef_detect():
        """Scan running processes for CEF apps.

        'apps' — processes with a CDP debug port (full automation possible).
        'passive_cef_apps' — CEF hosts without a debug port.  Each entry has
        ``pid``, ``name``, ``window_title``, ``detection_methods`` (any of
        ``cmdline`` / ``name`` / ``dll`` / ``cmdline-weak``), ``child_pids``,
        and ``cdp_access=False``.  Identified only — CDP is not available.
        """
        try:
            # Cached result check — skip expensive scans
            now = time.monotonic()
            fresh = request.args.get("fresh", "").lower() == "true"
            if not fresh and now - _cef_cache.get("ts", 0) < 30:
                return jsonify(_cef_cache["data"])

            apps = _scan_cef_processes()
            if not apps:
                apps = _probe_fallback_ports()
            try:
                passive = _scan_passive_cef_processes(fresh=fresh)
            except Exception as exc:
                _log(f"[CEF] passive scan error: {exc}")
                passive = []

            result = {
                "apps": apps,
                "count": len(apps),
                "passive_cef_apps": passive,
                "passive_count": len(passive),
            }
            _cef_cache["ts"] = time.monotonic()
            _cef_cache["data"] = result
            return jsonify(result)
        except Exception as exc:
            _log(f"[CEF] detect error: {exc}")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # Connection
    # -----------------------------------------------------------------------

    @app.route("/cef/connect", methods=["POST"])
    @require_auth
    def cef_connect():
        """Connect to a CEF app by debug port (or pid — port is auto-resolved).

        Body: {"port": 9222}  OR  {"pid": 12345}  OR  {"window": "NVIDIA App"}
        Optional: {"title_hint": "..."} to pick the right page when multiple tabs exist.
        """
        body = _json_body()
        if isinstance(body, tuple):   # error response from _json_body
            return body

        port = body.get("port")
        pid = body.get("pid")
        window_hint = body.get("window", "")
        title_hint = body.get("title_hint") or window_hint or None

        # Resolve port from pid / window name when not given directly
        if port is None:
            apps = _scan_cef_processes() or _probe_fallback_ports()
            if pid:
                for a in apps:
                    if a["pid"] == pid:
                        port = a["debug_port"]
                        break
            elif window_hint:
                hint = window_hint.lower()
                for a in apps:
                    if hint in a["name"].lower() or hint in a["window_title"].lower():
                        port = a["debug_port"]
                        break
            if port is None and apps:
                port = apps[0]["debug_port"]

        if port is None:
            return jsonify({"error": "No port resolved — pass 'port', 'pid', or 'window'"}), 400

        try:
            port = int(port)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid port: {port!r}"}), 400

        try:
            # Close any existing session on that port
            with _sessions_lock:
                old = _sessions.pop(port, None)
            if old:
                try:
                    old["ws"].close()
                except Exception:
                    pass

            ws, pages, page_id = _connect_to_port(port, title_hint)
            with _sessions_lock:
                _sessions[port] = {"ws": ws, "pages": pages, "page_id": page_id, "port": port}

            return jsonify({
                "connected": True,
                "port": port,
                "page_id": page_id,
                "pages": [{"id": p.get("id"), "title": p.get("title"), "url": p.get("url"), "type": p.get("type")} for p in pages],
            })
        except Exception as exc:
            _log(f"[CEF] connect error (port={port}): {exc}")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # DOM reading
    # -----------------------------------------------------------------------

    @app.route("/cef/dom", methods=["POST"])
    @require_auth
    def cef_dom():
        """Return the full DOM document tree for the connected CEF page.

        Body: {"port": 9222, "depth": 3}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        if not port:
            return jsonify({"error": "port required"}), 400
        depth = int(body.get("depth", 3))
        try:
            resp = _cdp(port, "DOM.getDocument", {"depth": depth})
            return jsonify({"dom": resp.get("result", {}).get("root"), "raw": resp})
        except Exception as exc:
            _log(f"[CEF] dom error: {exc}")
            return jsonify({"error": str(exc)}), 500

    @app.route("/cef/find", methods=["POST"])
    @require_auth
    def cef_find():
        """Find elements by CSS selector or text within the CEF page.

        Body: {"port": 9222, "selector": "button.download"}
        Optionally add "text" to filter results by visible text.
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        selector = body.get("selector", "*")
        text_filter = (body.get("text") or "").lower()
        if not port:
            return jsonify({"error": "port required"}), 400

        try:
            # Get document root
            doc_resp = _cdp(port, "DOM.getDocument", {"depth": 0})
            root_id = doc_resp.get("result", {}).get("root", {}).get("nodeId")
            if not root_id:
                return jsonify({"error": "Could not get DOM root"}), 500

            # Query all matching nodes
            qsa = _cdp(port, "DOM.querySelectorAll", {"nodeId": root_id, "selector": selector})
            node_ids = qsa.get("result", {}).get("nodeIds", [])

            elements = []
            for nid in node_ids[:50]:   # cap to avoid huge responses
                attrs_resp = _cdp(port, "DOM.getAttributes", {"nodeId": nid})
                attrs_list = attrs_resp.get("result", {}).get("attributes", [])
                attrs = dict(zip(attrs_list[::2], attrs_list[1::2]))
                outer_resp = _cdp(port, "DOM.getOuterHTML", {"nodeId": nid})
                outer = outer_resp.get("result", {}).get("outerHTML", "")

                if text_filter and text_filter not in outer.lower():
                    continue

                box_resp = _cdp(port, "DOM.getBoxModel", {"nodeId": nid})
                box = box_resp.get("result", {}).get("model")

                elements.append({
                    "nodeId": nid,
                    "attrs": attrs,
                    "outerHTML": outer[:500],
                    "box": box,
                })

            return jsonify({"elements": elements, "count": len(elements)})
        except Exception as exc:
            _log(f"[CEF] find error: {exc}")
            return jsonify({"error": str(exc)}), 500

    @app.route("/cef/text", methods=["POST"])
    @require_auth
    def cef_text():
        """Extract all visible text from the CEF page via JavaScript.

        Body: {"port": 9222}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        if not port:
            return jsonify({"error": "port required"}), 400
        try:
            js = "document.body ? document.body.innerText : document.documentElement.innerText"
            resp = _cdp(port, "Runtime.evaluate", {"expression": js, "returnByValue": True})
            text = resp.get("result", {}).get("result", {}).get("value", "")
            return jsonify({"text": text})
        except Exception as exc:
            _log(f"[CEF] text error: {exc}")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # Interaction
    # -----------------------------------------------------------------------

    @app.route("/cef/click", methods=["POST"])
    @require_auth
    def cef_click():
        """Click an element in the CEF page.

        Body: {"port": 9222, "selector": "button.download"}
        OR    {"port": 9222, "nodeId": 42}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        selector = body.get("selector")
        node_id = body.get("nodeId")
        if not port:
            return jsonify({"error": "port required"}), 400
        if not selector and not node_id:
            return jsonify({"error": "selector or nodeId required"}), 400

        try:
            if not node_id:
                doc_resp = _cdp(port, "DOM.getDocument", {"depth": 0})
                root_id = doc_resp["result"]["root"]["nodeId"]
                qs = _cdp(port, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
                node_id = qs.get("result", {}).get("nodeId")
                if not node_id:
                    return jsonify({"error": f"Element not found: {selector}"}), 404

            box_resp = _cdp(port, "DOM.getBoxModel", {"nodeId": node_id})
            model = box_resp.get("result", {}).get("model")
            if not model:
                return jsonify({"error": "Could not get bounding box for element"}), 500

            # content quad: [x1,y1, x2,y1, x2,y2, x1,y2]
            quad = model["content"]
            cx = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
            cy = (quad[1] + quad[3] + quad[5] + quad[7]) / 4

            for event_type in ("mousePressed", "mouseReleased"):
                _cdp(port, "Input.dispatchMouseEvent", {
                    "type": event_type,
                    "x": cx,
                    "y": cy,
                    "button": "left",
                    "clickCount": 1,
                })

            return jsonify({"clicked": True, "x": cx, "y": cy, "nodeId": node_id})
        except Exception as exc:
            _log(f"[CEF] click error: {exc}")
            return jsonify({"error": str(exc)}), 500

    @app.route("/cef/type", methods=["POST"])
    @require_auth
    def cef_type():
        """Type text into the focused element (or focus selector first).

        Body: {"port": 9222, "text": "hello", "selector": "#search"}
        selector is optional — if omitted, types into whatever has focus.
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        text = body.get("text", "")
        selector = body.get("selector")
        if not port:
            return jsonify({"error": "port required"}), 400

        try:
            # Optionally click to focus first
            if selector:
                doc_resp = _cdp(port, "DOM.getDocument", {"depth": 0})
                root_id = doc_resp["result"]["root"]["nodeId"]
                qs = _cdp(port, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
                node_id = qs.get("result", {}).get("nodeId")
                if node_id:
                    box_resp = _cdp(port, "DOM.getBoxModel", {"nodeId": node_id})
                    model = box_resp.get("result", {}).get("model")
                    if model:
                        quad = model["content"]
                        cx = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
                        cy = (quad[1] + quad[3] + quad[5] + quad[7]) / 4
                        for ev in ("mousePressed", "mouseReleased"):
                            _cdp(port, "Input.dispatchMouseEvent", {
                                "type": ev, "x": cx, "y": cy,
                                "button": "left", "clickCount": 1,
                            })

            for ch in text:
                _cdp(port, "Input.dispatchKeyEvent", {"type": "keyDown", "text": ch})
                _cdp(port, "Input.dispatchKeyEvent", {"type": "keyUp", "text": ch})

            return jsonify({"typed": True, "length": len(text)})
        except Exception as exc:
            _log(f"[CEF] type error: {exc}")
            return jsonify({"error": str(exc)}), 500

    @app.route("/cef/evaluate", methods=["POST"])
    @require_auth
    def cef_evaluate():
        """Evaluate JavaScript in the CEF page and return the result.

        Body: {"port": 9222, "expression": "document.title"}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        expression = body.get("expression", "")
        if not port:
            return jsonify({"error": "port required"}), 400
        if not expression:
            return jsonify({"error": "expression required"}), 400

        try:
            resp = _cdp(port, "Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            })
            result = resp.get("result", {})
            exc_detail = result.get("exceptionDetails")
            if exc_detail:
                return jsonify({"error": "JS exception", "details": exc_detail}), 400
            value = result.get("result", {}).get("value")
            return jsonify({"result": value, "raw": result.get("result", {})})
        except Exception as exc:
            _log(f"[CEF] evaluate error: {exc}")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # Smart one-shot helper
    # -----------------------------------------------------------------------

    @app.route("/cef/smart-click", methods=["POST"])
    @require_auth
    def cef_smart_click():
        """Auto-detect the CEF port for a named window, connect, find a button by text, and click it.

        Body: {"window": "NVIDIA App", "text": "Download"}
        Optional: {"port": 9222} to skip auto-detection.
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        window_name = body.get("window", "")
        button_text = body.get("text", "")
        port = body.get("port")

        if not button_text:
            return jsonify({"error": "text required (button label to click)"}), 400

        try:
            # Resolve port
            if not port:
                apps = _scan_cef_processes() or _probe_fallback_ports()
                if window_name:
                    hint = window_name.lower()
                    for a in apps:
                        if hint in a["name"].lower() or hint in a["window_title"].lower():
                            port = a["debug_port"]
                            break
                if port is None and apps:
                    port = apps[0]["debug_port"]
            if port is None:
                return jsonify({"error": f"Could not find a CEF process for '{window_name}'"}), 404

            # Connect (or reuse)
            with _sessions_lock:
                have_session = port in _sessions
            if not have_session:
                ws, pages, page_id = _connect_to_port(port, window_name or None)
                with _sessions_lock:
                    _sessions[port] = {"ws": ws, "pages": pages, "page_id": page_id, "port": port}

            # Find the element by text using JS (most reliable across frameworks)
            js = f"""
(function() {{
    var all = document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]');
    var target = Array.from(all).find(function(el) {{
        return el.innerText && el.innerText.toLowerCase().includes({json.dumps(button_text.lower())});
    }});
    if (!target) return null;
    var r = target.getBoundingClientRect();
    return {{x: r.left + r.width/2, y: r.top + r.height/2, text: target.innerText.trim()}};
}})()
"""
            resp = _cdp(port, "Runtime.evaluate", {"expression": js, "returnByValue": True})
            value = resp.get("result", {}).get("result", {}).get("value")
            if not value:
                return jsonify({"error": f"Button with text '{button_text}' not found in CEF page on port {port}"}), 404

            cx, cy = float(value["x"]), float(value["y"])
            for event_type in ("mousePressed", "mouseReleased"):
                _cdp(port, "Input.dispatchMouseEvent", {
                    "type": event_type, "x": cx, "y": cy,
                    "button": "left", "clickCount": 1,
                })

            return jsonify({
                "clicked": True,
                "port": port,
                "window": window_name,
                "button_text": value.get("text", button_text),
                "x": cx,
                "y": cy,
            })
        except Exception as exc:
            _log(f"[CEF] smart-click error: {exc}")
            return jsonify({"error": str(exc)}), 500

    # -----------------------------------------------------------------------
    # Session management
    # -----------------------------------------------------------------------

    @app.route("/cef/sessions", methods=["POST"])
    @require_auth
    def cef_sessions():
        """List all active CEF sessions."""
        with _sessions_lock:
            sessions = [
                {"port": s["port"], "page_id": s["page_id"],
                 "pages": len(s["pages"])}
                for s in _sessions.values()
            ]
        return jsonify({"sessions": sessions, "count": len(sessions)})

    @app.route("/cef/disconnect", methods=["POST"])
    @require_auth
    def cef_disconnect():
        """Disconnect from a CEF session.

        Body: {"port": 9222}
        """
        body = _json_body()
        if isinstance(body, tuple):
            return body
        port = body.get("port")
        if not port:
            return jsonify({"error": "port required"}), 400
        try:
            port = int(port)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid port: {port!r}"}), 400
        with _sessions_lock:
            sess = _sessions.pop(port, None)
        if sess:
            try:
                sess["ws"].close()
            except Exception:
                pass
            return jsonify({"disconnected": True, "port": port})
        return jsonify({"disconnected": False, "error": f"No session on port {port}"}), 404
