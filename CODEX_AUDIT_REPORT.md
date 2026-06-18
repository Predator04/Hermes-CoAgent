# Hermes CoAgent v7.0 Code Audit Report

Generated: 2026-06-18
Scope: Current working tree review of `auth.py`, `hermes_coagent.py`, `shared.py`, `routes_mouse.py`, `routes_ocr.py`, `routes_uia.py`, `routes_file.py`, `routes_media.py`, `coagent_features.py`, `computer_use_mcp.py`, `uia_engine.py`, and `tray_icon.py`.

Note: This report reflects the current dirty working tree. `git status --short --untracked-files=all` shows modified `auth.py`, `hermes_coagent.py`, `launch_all.ps1`, `start_coagent.bat`, plus untracked `.token`, `CODEX_AUDIT_PROMPT.md`, and `nul`.

## Critical Issues

### 1. `--token=KEY` launches can silently run without auth

File: `hermes_coagent.py:255-261`

```python
if "--allow-external" in sys.argv:
    bind_host = "0.0.0.0"
...
if "--secure" in sys.argv or "--token" in sys.argv or "--allow-external" in sys.argv:
    _init_auth(port, COAGENT_DIR)
    _console("  Auth: enabled")
```

`auth.py` supports `--token=KEY`, but `hermes_coagent.py` checks only for the literal `"--token"` argument. A normal `python hermes_coagent.py --token=KEY` start will not call `_init_auth()`, so all `@require_auth` wrappers become pass-through because `AUTH_ENABLED` remains false.

The same block also logs `Auth: enabled` for `--allow-external` even though `auth.init_auth()` does not enable auth unless `--secure` or a token is present. That makes an externally bound, unauthenticated desktop-control server easy to start by accident.

Fix: call `_init_auth()` when any arg starts with `--token=`, and refuse `--allow-external` unless `auth.AUTH_ENABLED` is actually true after initialization. Do not log enabled auth until that state is verified.

### 2. Sensitive desktop read routes bypass auth

Files: `routes_ocr.py`, `routes_uia.py`, `routes_media.py`, `hermes_coagent.py`

```python
# routes_ocr.py:197-218
@app.route("/screen", methods=["GET"])
def route_screen():
...
@app.route("/screen/base64", methods=["GET"])
def route_screen_b64():
```

```python
# routes_ocr.py:260-283
@app.route("/crop", methods=["POST"])
def route_crop():
...
@app.route("/describe", methods=["GET"])
def route_describe():
```

```python
# routes_uia.py:32-46
@app.route("/uia/tree", methods=["GET"])
def route_uia_tree():
...
@app.route("/uia/find/<name>", methods=["GET"])
def route_uia_find(name):
```

```python
# routes_uia.py:129-158
@app.route("/som/screenshot", methods=["GET"])
def route_som_screenshot():
    ...
    return jsonify({"labeled_screenshot": base64.b64encode(buf.getvalue()).decode(), "elements": elements})
```

```python
# routes_media.py:123-138
@app.route("/clipboard/get", methods=["GET"])
def route_clipboard_get():
...
@app.route("/clipboard/set", methods=["POST"])
def route_clipboard_set():
```

```python
# hermes_coagent.py:227-238
@app.route("/logs", methods=["GET"])
def route_logs():
    ...
    log_text = SERVER_LOG.read_text(encoding="utf-8", errors="replace")
    return Response(f"<pre>{last_n}</pre>", mimetype="text/html")
```

When secure mode is enabled, these routes still expose screenshots, OCR text, UI tree/window titles, clipboard contents, SOM overlays, and logs without requiring a bearer token. This is a high-impact privacy and control-channel leak, especially if the server is ever bound externally.

Fix: add default-deny global auth with a small explicit allowlist (`/ping`, auth bootstrap routes if needed), or decorate every sensitive read route with `@require_auth`. Logs should also be returned as escaped text or JSON, not raw HTML.

### 3. System-mutating routes bypass auth

Files: `routes_file.py`, `routes_media.py`, `routes_mouse.py`

```python
# routes_file.py:121-143
@app.route("/power/sleep", methods=["POST"])
def route_power_sleep():
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], timeout=5)
...
@app.route("/power/restart", methods=["POST"])
def route_power_restart():
    subprocess.run(["shutdown", "/r", "/t", "10"], timeout=5)
```

```python
# routes_media.py:53-74
@app.route("/windows/activate", methods=["POST"])
def route_win_activate():
    ...
    ctypes.windll.user32.SetForegroundWindow(hwnd)
```

```python
# routes_media.py:77-102
@app.route("/wallpaper/set", methods=["POST"])
def route_wallpaper_set():
...
@app.route("/wallpaper/random", methods=["POST"])
def route_wallpaper_random():
```

```python
# routes_media.py:168-203
@app.route("/scheduler/add", methods=["POST"])
def route_scheduler_add():
...
@app.route("/scheduler/run", methods=["POST"])
def route_scheduler_run():
```

```python
# routes_media.py:347-364
@app.route("/launch/ai", methods=["POST"])
def route_launch_ai():
    ...
    else: subprocess.Popen([exe])
```

```python
# routes_mouse.py:215-224
@app.route("/emergency/stop", methods=["POST"])
def route_emergency_stop():
    state.emergency_stop = True
...
@app.route("/emergency/resume", methods=["POST"])
def route_emergency_resume():
    state.emergency_stop = False
```

Power management, window focus, wallpaper changes, scheduler changes, app launch, clipboard mutation, macro state, recording controls, cursor controls, and emergency stop/resume are state-changing operations. Several currently have no `@require_auth`.

Fix: protect all POST routes that mutate desktop/server state. `emergency/status` can stay open if desired, but stop/resume should require auth or a separate local-only emergency channel.

### 4. `/auth/token/reset` is unauthenticated and can roll auth state back to the saved token

File: `auth.py:145-160`

```python
@app.route('/auth/token/reset', methods=['GET', 'POST'])
def auth_token_reset():
    """Reset token from saved file (no auth required)."""
    global AUTH_TOKEN, AUTH_ENABLED
    tp = _token_path()
    ...
    AUTH_TOKEN = saved
    AUTH_ENABLED = True
```

Any caller can force the server to reload `.token` without presenting the current token. If the current in-memory token was regenerated, this rolls auth back to an older disk token. Combined with the unignored `.token` file in the repo, this creates a practical recovery path for stale token material.

Fix: make reset `POST` only and require the current bearer token, or remove this endpoint. If a local recovery endpoint is needed, bind it to loopback and require an OS-local secret or interactive confirmation.

### 5. TTS route has PowerShell command injection via interpolated text

File: `routes_media.py:152-158`

```python
ps_script = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Speak("{text.replace('"', '""')}")
'''
subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_script], timeout=30,
```

Only double quotes are doubled. PowerShell double-quoted strings still expand subexpressions and escape sequences, so attacker-controlled `text` can alter the command executed by `-Command`. The route has `@require_auth`, but this is still a command-injection bug in an endpoint explicitly intended to process arbitrary text.

Fix: avoid building PowerShell source with user text. Pass text through stdin, a temporary UTF-8 file, or an environment variable, and read it as data inside a static script. Prefer a direct Python TTS library call if available.

### 6. Macro names allow path traversal and macro save/run is unauthenticated

File: `routes_media.py:218-235`, `routes_media.py:256-263`

```python
@app.route("/macro/save", methods=["POST"])
def route_macro_save():
    name = d.get("name", f"macro_{int(time.time())}")
    ...
    (MACROS_DIR / f"{name}.json").write_text(...)
```

```python
@app.route("/macro/run", methods=["POST"])
def route_macro_run():
    name = d.get("name", "")
    path = MACROS_DIR / f"{name}.json"
    ...
    macro = json.loads(path.read_text())
```

```python
@app.route("/macro/delete", methods=["POST"])
@require_auth
def route_macro_delete():
    name = d.get("name", "")
    path = MACROS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
```

`name` is used directly in a path. Values containing `..` or path separators can escape `MACROS_DIR` while still adding the `.json` suffix. Save and run are also unauthenticated, so a caller can create or execute macro definitions without a token when auth is otherwise expected.

Fix: require auth on all macro mutation/execution routes and validate names with a strict regex such as `^[A-Za-z0-9_.-]{1,80}$`. Resolve the final path and verify it remains under `MACROS_DIR` before read/write/delete.

### 7. Token file exists in the working tree and is not ignored

Files: `.token`, `.gitignore`

```text
git status --short --untracked-files=all
?? .token
?? nul
```

`.gitignore` currently contains cache/log/generated entries but no `.token` rule:

```gitignore
*.pyc
__pycache__/
screenshots/
macros/
*.apk
screen_temp*.png
test_mcp*.py
*.log
.codex_path
*.bat
*.vbs
```

The local `.token` is 64 bytes and untracked. It is not committed now, but it is one `git add -A` away from being committed.

Fix: add `.token`, `.token_*`, and `nul` to `.gitignore`; remove the local `nul` artifact; rotate the token if it was ever shared or committed.

## Performance Optimizations

### 1. `shared.py` performs a PowerShell network query at import time

File: `shared.py:34-40`

```python
HOST_IP = "172.21.192.1"
try:
    r = subprocess.run(
        ["powershell.exe", "-Command",
         "(Get-NetIPAddress -InterfaceAlias 'vEthernet (WSL)' -AddressFamily IPv4).IPAddress"],
        capture_output=True, text=True, timeout=5
    )
```

Every import of `shared.py` can spend up to five seconds in PowerShell before the Flask app is fully initialized. This is cold-start cost in a module imported by most routes.

Before: eager subprocess on import.

After: lazy `get_host_ip()` with cached result, shorter timeout, and only call it in `/screen/diag` or whichever route actually needs it.

### 2. UIA snapshot creates daemon threads per request and cannot cancel slow crawls

File: `uia_engine.py:206-256`

```python
def _run():
    ...
    ct = threading.Thread(target=_crawl_window_children, daemon=True)
    ct.start()
    ct.join(timeout=2.0)
...
t = threading.Thread(target=_run, daemon=True)
t.start()
t.join(timeout=timeout)
```

Each snapshot can create a top-level daemon thread plus child crawl threads. Timed-out child threads keep running in the background until pywinauto returns. Under repeated `/uia/tree`, `/som/screenshot`, and `/uia/element/find` calls, this can stack up.

Before: request-local daemon threads with no concurrency cap.

After: one shared bounded executor or a serialized UIA worker with backpressure, plus a short cache for read-only UIA snapshots.

### 3. OCR PowerShell fallback leaks temp files on timeout/error

File: `routes_ocr.py:116-168`

```python
tmp_img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
...
tmp_ps1 = tempfile.NamedTemporaryFile(suffix=".ps1", mode="w", delete=False)
...
r = subprocess.run([...], timeout=30, ...)
os.unlink(tmp_ps1_path)
...
except subprocess.TimeoutExpired:
    return {"success": False, "error": "PowerShell timeout"}
```

The temp script is removed only on the success path after `subprocess.run()`. The temp image is removed inside the generated PowerShell, so it is left behind if PowerShell fails before `Remove-Item` or times out.

Before: cleanup is split between Python success path and generated script.

After: wrap the subprocess call in `finally` and unlink both `tmp_ps1_path` and `tmp_img_path` from Python.

### 4. File search can walk a large profile tree without time or directory limits

File: `routes_media.py:304-326`

```python
limit = min(d.get("limit", 50), 200)
...
for root, dirs, files in os.walk(search_path):
```

The result count is capped, but traversal cost is not. A pattern with few matches can scan a large user profile and tie up a Waitress worker.

Before: unbounded `os.walk()`.

After: add `max_seconds`, `max_dirs`, optional depth, and skip known heavy directories such as `.git`, `node_modules`, browser caches, and virtualenvs by default.

### 5. `/logs` reads the entire log file before slicing the tail

File: `hermes_coagent.py:233-238`

```python
log_text = SERVER_LOG.read_text(encoding="utf-8", errors="replace")
log_lines = log_text.split("\n")
last_n = "\n".join(log_lines[-limit:])
```

The shared logger rotates at 5 MB, so this is bounded, but it is still unnecessary work on a hot diagnostic endpoint.

Before: full-file read and split.

After: use `collections.deque(f, maxlen=limit)` or a small tail reader.

## Code Quality

### 1. `routes_v63.py` is present but not registered, and it would fail if registered as written

File: `hermes_coagent.py:111-121`

```python
from routes_mouse import register_routes as reg_mouse
from routes_ocr import register_routes as reg_ocr
from routes_uia import register_routes as reg_uia
from routes_file import register_routes as reg_file
from routes_media import register_routes as reg_media

reg_mouse(app, state, require_auth)
...
reg_media(app, state, require_auth)
```

File: `routes_v63.py:117-124`

```python
def _add(app, rules, func, methods=None, auth=False):
    view = shared.require_auth(func) if auth else func
...
def register_routes(app):
    _add(app, ["/cursor/enable"], route_cursor_enable, methods=["POST"], auth=True)
```

`hermes_coagent.py` never imports or calls `routes_v63.register_routes()`. If it did, `routes_v63.py` references `shared.require_auth`, but `shared.py` does not define that symbol. Its `register_routes(app)` signature also does not match the other route modules that accept `(app, state, require_auth)`.

Fix: either delete `routes_v63.py` and move real feature handlers into `routes_media.py`, or register it with the same signature and use the passed `require_auth`. Avoid duplicate URL rules already defined in `routes_uia.py` and `routes_media.py`.

### 2. v6.3/v7 feature endpoints are stubs instead of calling `coagent_features.py`

File: `routes_media.py:399-417`

```python
@app.route("/cursor/enable", methods=["POST"])
def route_cursor_enable():
    return jsonify({"status": "ok", "message": "cursor control via coagent_features"})
...
@app.route("/recording/start", methods=["POST"])
def route_recording_start():
    return jsonify({"status": "recording", "dir": str(SCREENSHOTS_DIR)})
```

The advertised cursor and recording routes do not call `coagent_features.cursor_set_enabled()`, `recording_start()`, or related functions. This makes `/features`, `/cursor/status`, and `/recording/status` misleading.

Fix: wire these routes to `coagent_features.py` or remove them from `/version` features until implemented.

### 3. Cursor overlay fix is incomplete

File: `coagent_features.py:30-61`

```python
_CURSOR_COLOR = "#FF4400"  # Default orange-red
_CURSOR_SIZE = 32
...
hwnd = ctypes.windll.user32.CreateWindowExW(
    0x80000 | 0x20,  # WS_EX_LAYERED | WS_EX_TRANSPARENT
...
ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0xFF4400, 180, 0x2)
```

The v7.0 prompt expected `_CURSOR_SIZE = 48` and extended style including `WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOPMOST`. Current code uses size 32 and only `WS_EX_LAYERED | WS_EX_TRANSPARENT` at creation time. `SetWindowPos(..., -1, ...)` later makes it topmost, but the no-activate extended style is still missing.

Fix: set a named style constant with all required flags and update the size if 48 is the intended v7 default.

### 4. Direct WinRT OCR path does not fall back for ABI/runtime mismatches

File: `routes_ocr.py:76-112`

```python
ras = streams.InMemoryRandomAccessStream()
ras.write_async(buf.read()).get()
...
except ImportError:
    try:
        return _windows_ocr_powershell(pil_image)
...
except Exception as e:
    return {"success": False, "error": str(e)}
```

Only `ImportError` falls through to the PowerShell OCR path. Attribute and type errors from `winrt-runtime` async API differences return an error directly, so the intended fallback does not run.

Fix: catch `AttributeError` and `TypeError` around the direct WinRT calls and fall back to `_windows_ocr_powershell()`. Add the requested WinRT version diagnostic as a helper used in `/screen/diag` or OCR errors.

### 5. MCP `--port` is parsed but not used

File: `computer_use_mcp.py:662-668`

```python
if "--http" in sys.argv or "--sse" in sys.argv:
    port = 8001
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])
    print(f"[MCP] Running SSE server on port {port}")
    mcp.run(transport="sse")
```

The selected `port` is only printed. It is not passed to `mcp.run()`, so `--port` does not affect the actual listener. The top docstring still says `--http` is SSE on `:8000`, while the v7 code prints `8001`.

Fix: pass host and port to FastMCP if the SDK supports it, or configure FastMCP settings before `run()`. Align the docstring with the real default.

### 6. `auth.py` known f-string issue is not present

File: `auth.py:80-84`

```python
pre = token[:16]
suf = token[-8:]
auth_type = "Secure mode" if "--secure" in sys.argv else "Token auth"
print(f"[Auth] {auth_type} enabled - token: {pre}...{suf}")
print(f"[Auth]   Use header: Authorization: Bearer {pre}...{suf}")
```

The suspected `{prefi...}` string literal issue is not present in the current file. Line 84 is a valid f-string using `pre` and `suf`.

### 7. No direct `shell=True` or `os.system` was found in the reviewed Python files

The reviewed Python code generally uses list-form `subprocess.run()` / `Popen()` and `shell=False` where explicit. The notable exception is not `shell=True`; it is PowerShell source construction via `-Command` in the TTS route.

## Quick Wins

1. Add `.token`, `.token_*`, and `nul` to `.gitignore`; remove the local `nul` artifact; rotate the local token if it may have been exposed.

2. Fix `hermes_coagent.py` auth startup:

```python
has_token_arg = any(a == "--token" or a.startswith("--token=") for a in sys.argv)
if "--secure" in sys.argv or has_token_arg or "--allow-external" in sys.argv:
    _init_auth(port, COAGENT_DIR)
if bind_host == "0.0.0.0" and not auth.AUTH_ENABLED:
    raise SystemExit("--allow-external requires --secure or --token=KEY")
```

3. Add `@require_auth` immediately to unauthenticated POST routes that mutate state: `/power/*`, `/clipboard/set`, `/windows/activate`, `/wallpaper/*`, `/scheduler/*`, `/macro/save`, `/macro/run`, `/macro/record`, `/replay`, `/voice/toggle`, `/launch/ai`, `/cursor/*`, `/recording/start`, `/recording/stop`, `/wait/*`, `/stabilize`, `/emergency/stop`, and `/emergency/resume`.

4. Put all screenshot/OCR/UIA/clipboard/log routes behind auth unless a route is explicitly intended as public health metadata.

5. Replace TTS `-Command` interpolation with stdin/temp-file data passing.

6. Add macro name validation and final-path containment checks.

7. Add `finally` cleanup around OCR temp files.

8. Wire or remove `routes_v63.py`; do not leave duplicate stub endpoints in `routes_media.py`.

## Summary

Overall health score: **D**

The v7.0 modular split is present, but the auth model regressed from the previous global-protection approach into inconsistent per-route decorators. Core mouse/key/file execution routes are mostly protected, but many equally sensitive routes are not. There are also two concrete injection/path traversal bugs and a startup auth bug that can make secure launches silently insecure.

Top 3 things to fix:

1. Restore default-deny auth and fix startup auth initialization for `--token=KEY` and `--allow-external`.
2. Protect screenshot/OCR/UIA/clipboard/log/power/macro/scheduler routes with auth.
3. Fix TTS PowerShell interpolation, macro path traversal, and `.token` ignore/rotation.
