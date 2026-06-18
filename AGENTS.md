# Hermes CoAgent v7.0 — Complete Refactor & Improvement

You are Codex. You have **300 seconds**. Follow this plan EXACTLY. Make ALL changes. Commit at the end.

## RULES

1. **NEVER import `require_auth` from `auth` inside `if __name__ == "__main__"` blocks** — the `require_auth` wrapper from `hermes_coagent.py`'s module-level `from auth import require_auth as _require_auth` is the canonical one. Do NOT shadow it.
2. **NEVER use blanket `taskkill /f /im python*`** — it kills Hermes itself.
3. **NEVER create files on `C:\Users\Admin\Desktop\`** — everything stays in `C:\Users\Admin\Desktop\Hermes CoAgent\`.
4. **No pyautogui stubs or import changes** — the current stub system works.
5. **All changes must be backward-compatible** — same endpoints, same JSON shapes.
6. **Preserve all existing comments, docstrings, and version history headers.**
7. **Do NOT change the Waitress server config, singleton mutex, or tray icon launch mechanism** — those work.
8. **Auth whitelist must stay at 13 AUTH_EXEMPT_PREFIXES and 20+ AUTH_EXEMPT_PATHS** — Codex resets these, don't.
9. **Do NOT modify `tray_icon.py`** — it's fine.
10. **Do NOT modify `auth.py`** — it's fine.

## WHAT TO BUILD

### 1. SPLIT THE 3131-LINE MONOLITH INTO MODULES

`hermes_coagent.py` is 3131 lines. Split it:

**Create `routes_mouse.py` — Mouse & Keyboard routes** (~150 lines)
Move these routes AND their helper functions:
- `/mouse/move`, `/mouse/click`, `/mouse/dblclick`, `/mouse/rclick`, `/mouse/drag`, `/mouse/scroll`
- `/key/type`, `/key/press`
- `/chain`, `/act`
- `/cursor/pos`, `/copilot/mode`
- `/input/send`
- Helper: `_background_sendinput()`, `_foreground_pyautogui()`, `_mouse_action()`, `_key_action()`, `_execute_action_wrapper()`, `_build_action()`
- Helper: `_json_body()`, `_log()`, `_ensure_session1()`, `_sanitize_path()`, `_sanitize_cmd()`, `_interactive_task_xml()` (these are shared utilities — import from module)

**Create `routes_ocr.py` — OCR & Screen Routes** (~200 lines)
Move these:
- `/ocr/find`, `/visual/find`, `/crop`, `/describe`
- `_windows_ocr()`, `_windows_ocr_powershell()`, `ocr_find_text()`, `ocr_find_uia()`, `_ocr_cached_result()`
- `_capture_raw()`, `_grab_screen_bytes()`, `_grab_screen_mss()`, `_MSS_AVAILABLE`, `_MSS_LOCK`, `SCREENSHOT_CACHE_TTL`
- Screenshot routes: `/screen`, `/screen/jpeg`, `/screen/base64`, `/screen/fresh`, `/screen/diag`

**Create `routes_uia.py` — UIA & SOM Routes** (~250 lines)
Move these:
- `/uia/tree`, `/uia/snapshot`, `/uia/find/<name>`, `/uia/click`, `/uia/find-cmb`, `/uia/diag`
- `/som/screenshot`, `/som/image`, `/som/cache/clear`, `/som/bridge`, `/som/per-window`, `/som/point`
- `/uia/accel-reg`, `/uia/window-tree`, `/uia/element/find`, `/uia/element/click-by-name`, `/uia/element/click-by-index`
- `/wait/element`, `/wait/element-gone`, `/stabilize`
- Helper: `_get_uia_engine()`, SOM diff cache logic

**Create `routes_file.py` — File, App & Power Routes** (~120 lines)
Move these:
- `/file/list`, `/file/read`, `/file/write`, `/file/delete`
- `/app/open`, `/app/run`, `/launch/ai`
- `/power/sleep`, `/power/shutdown`, `/power/restart`, `/power/lock`, `/power/cancel`

**Create `routes_media.py` — Wallpaper, Scheduler, Macro, Voice, TTS, etc** (~120 lines)
Move these:
- `/wallpaper/set`, `/wallpaper/cycle`, `/wallpaper/random`
- `/monitors/layout`, `/windows`, `/windows/activate`
- `/clipboard/get`, `/clipboard/set`
- `/tts/speak`
- `/scheduler/*`
- `/macro/*`, `/replay`
- `/voice/toggle`
- `/tunnel/*`
- `/search/files`
- `/emergency/*`
- `/monitors`, `/stats`, `/history`, `/events`

**Create `routes_v63.py` — v6.3 Feature Routes** (~80 lines)
Move these from coagent_features integration:
- `/cursor/enable`, `/cursor/style`, `/cursor/status`
- `/recording/start`, `/recording/stop`, `/recording/status`
- `/features`
- `/uia/element/click-by-name`, `/uia/element/click-by-index` (move FROM routes_uia OR keep — avoid duplicates)
- `/wait/element`, `/wait/element-gone`, `/stabilize` (same — avoid duplication)

**Create `shared.py` — Shared utilities** (~80 lines)
Extract these helpers from `hermes_coagent.py`:
```python
"""Shared utilities for CoAgent route modules."""

import sys, os, json, subprocess, time, traceback, functools, re, ctypes
from io import BytesIO
from pathlib import Path
from datetime import datetime
from flask import jsonify

COAGENT_DIR = Path(__file__).parent.resolve()
SERVER_LOG = COAGENT_DIR / "coagent_server.log"

def _json_body():
    from flask import request
    try:
        return request.get_json(force=True, silent=True) or {}
    except:
        return {}

def _log(msg):
    import traceback
    try:
        # Rotate at 5MB
        if SERVER_LOG.exists() and SERVER_LOG.stat().st_size > 5 * 1024 * 1024:
            for i in range(4, 0, -1):
                old = SERVER_LOG.with_suffix(f".log.{i}")
                if old.exists():
                    old.rename(SERVER_LOG.with_suffix(f".log.{i+1}"))
            SERVER_LOG.rename(SERVER_LOG.with_suffix(".log.1"))
        with SERVER_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except:
        pass

def _ensure_session1():
    try:
        pid = os.getpid()
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid}).SessionId"],
            capture_output=True, text=True, timeout=5
        )
        sid = int(r.stdout.strip())
        return sid
    except:
        return 0

def _sanitize_path(requested_path):
    allowed = [
        os.environ.get("USERPROFILE", "").lower(),
        os.environ.get("TEMP", "").lower(),
        str(COAGENT_DIR).lower(),
    ]
    resolved = os.path.realpath(requested_path).lower()
    for a in allowed:
        if a and resolved.startswith(a):
            return resolved
    raise ValueError("Path not allowed")

def _sanitize_cmd(cmd):
    blocked = re.compile(r'[;&|`$(){}\[\]]')
    if blocked.search(cmd):
        raise ValueError("Shell metacharacters not allowed")
    return cmd

def _interactive_task_xml(exe, args, author="Admin", execution_limit="PT0S", working_dir=""):
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>{author}</Author></RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>{execution_limit}</ExecutionTimeLimit>
    <AllowStartOnRemoteDesktops>true</AllowStartOnRemoteDesktops>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author">
    <InteractiveContext>Author</InteractiveContext>
    <Exec>
      <Command>{exe}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
```

**In `hermes_coagent.py` (the main file):** Keep:
- Flask app creation
- Singleton mutex
- Auth setup
- Global error handlers
- CoPilotState dataclass
- Route registration (import from modules and register)
- `_start_tray()`
- Startup banner + Waitress serve
- `require_auth` wrapper
- SHORT ALIAS routes (the dict at ~line 3080)
- System tray launch

Import pattern:
```python
# After app creation and auth setup:
from routes_mouse import register_routes as register_mouse
from routes_ocr import register_routes as register_ocr
from routes_uia import register_routes as register_uia
from routes_file import register_routes as register_file
from routes_media import register_routes as register_media
from routes_v63 import register_routes as register_v63

register_mouse(app)
register_ocr(app)
register_uia(app)
register_file(app)
register_media(app)
register_v63(app)
```

Each `register_routes(app)` function receives the Flask app and applies `@app.route(...)` decorators internally. Each function also receives `CoPilotState` and `require_auth` if needed.

Each route module imports `from shared import _json_body, _log, _sanitize_path, _sanitize_cmd, _interactive_task_xml` and accesses the global state through a passed-in `state` object.

**IMPORTANT: Do NOT create circular imports.** `shared.py` imports NOTHING from route modules.

**Line count impact:** hermes_coagent.py goes from 3131 → ~600 lines. 5 new modules totaling ~800 lines. Overall codebase stays ~same size but organized.

### 2. RELAUNCH COAGENT (the server is down)

After all code changes:
1. Kill any existing python processes that are CoAgent-related (NOT blanket kill)
2. Write and run a verification script
3. Launch CoAgent via schtasks targeting Session 1
4. Verify with curl to /ping

### 3. FIX AGENT CURSOR OVERLAY — Currently broken

In `coagent_features.py`, the cursor overlay `_ensure_cursor_window()` creates a WS_EX_LAYERED window. This requires the `PULSE_SIZE` constant to be defined. Check that `_CURSOR_SIZE = 48` and `_CURSOR_COLOR = 0xFF4400` are set correctly.

The `set_cursor_position(x, y)` function calls `SetWindowPos` but the overlay window needs `WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOPMOST`. Verify these are set in `_ensure_cursor_window()`.

Fix: Add `ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 200, 2)` (2 = LWA_ALPHA) and ensure `WS_EX_LAYERED` is in the extended style.

### 4. FIX WinRT OCR (the Windows OCR pathway)

The `_windows_ocr()` function in `routes_ocr.py` uses `winrt.windows.media.ocr` etc. If these packages have ABI mismatch issues:

In `_windows_ocr()`, add a try/except around the `InMemoryRandomAccessStream.write_async()` call — the WinRT async pattern differs between winrt-runtime v2.x and v3.x. If v3.x, use `asyncio.get_event_loop().run_until_complete()` instead of `.get()`.

Actually, the simplest fix: add a diagnostic function `_check_winrt_version()` that prints the winrt-runtime version, and in `_windows_ocr()`, catch `AttributeError` and `TypeError` on the stream write, then fall through to the PowerShell fallback.

### 5. ADD SSE TRANSPORT TO MCP SERVER

In `computer_use_mcp.py`, add an SSE mode that listens on port 8001:
```python
if "--sse" in sys.argv or "--http" in sys.argv:
    # Run as SSE server on port 8001
    port = 8001
    mcp.run(transport="sse", host="0.0.0.0", port=port)
```

Currently the HTTP mode uses SSE transport on port 8000. Keep that. The `--sse` flag should just be an alias for `--http`.

Also add a `--port` argument:
```python
if "--port" in sys.argv:
    idx = sys.argv.index("--port")
    port = int(sys.argv[idx + 1])
```

### 6. FIX THREAD POOL FROM 2 TO 4

In both SOM routes in `hermes_coagent.py` (lines where `ThreadPoolExecutor(max_workers=2)` appears), bump to `max_workers=4`.

Search: `max_workers` appears in these contexts:
- `concurrent.futures.ThreadPoolExecutor(max_workers=2)` in SOM routes
Change to `max_workers=4`.

### 7. ADD HEALTH WATCHDOG SCRIPT

Create `watchdog_coagent.ps1` in `C:\Users\Admin\Desktop\Hermes CoAgent\`:
```powershell
# watchdog_coagent.ps1 — Checks CoAgent health every 30s, restarts if down
$ErrorActionPreference = "SilentlyContinue"
$log = "$PSScriptRoot\watchdog.log"
$url = "http://127.0.0.1:9123/ping"
$checkInterval = 30

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

while ($true) {
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            # Healthy — do nothing
        }
    } catch {
        Write-Log "CoAgent DOWN. Restarting..."
        # Kill old instances
        Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -match "hermes_coagent"
        } | Stop-Process -Force
        
        Start-Sleep 2
        
        # Launch via batch
        $batch = "$PSScriptRoot\start_coagent.bat"
        if (Test-Path $batch) {
            Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$batch`"" -WindowStyle Hidden
            Write-Log "Launched via start_coagent.bat"
        }
        
        Start-Sleep 5
        
        # Verify
        try {
            $r = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                Write-Log "CoAgent restarted OK"
            }
        } catch {
            Write-Log "CoAgent restart FAILED"
        }
    }
    Start-Sleep $checkInterval
}
```

Run this via a hidden scheduled task or silently.

### 8. UPDATE VERSION TO v7.0

Bump ALL version strings in ALL files:
- `hermes_coagent.py`: `VERSION = "6.4"` → `"7.0"`, build date to today
- `computer_use_mcp.py`: version string in top docstring
- `tray_icon.py`: tray tooltip from "v6.2" to "v7.0"
- `uia_engine.py`: docstring version
- `dashboard.html`: version in header
- `ROUTE_MAP.py`: docstring version

Add "/version" feature list entries for:
- "modular_routes" — route monolith split into modules
- "sse_mcp" — SSE transport for MCP
- "health_watchdog" — auto-restart watchdog
- "thread_pool_4" — increased thread pool

### 9. UPDATE SKILL.md (WINDOWS-DESKTOP-CONTROL)

Add v7.0 section to `/home/predator04/.hermes/skills/devops/windows-desktop-control/SKILL.md`:

| Version | Date | Description |
|---------|------|-------------|
| **v7.0** | 2026-06-18 | **Modular Refactor.** Monolith split into 6 route modules + shared utilities. SSE MCP transport. Health watchdog. Thread pool 2→4. Agent cursor fix. WinRT OCR diagnostic. |

### 10. CONDITIONAL: ONLY if git status shows trackable changes

After all code changes, commit with message:
```
v7.0: Modular refactor + watchdog + SSE + fixes

- Split 3131-line hermes_coagent.py into 6 route modules + shared.py
- Added health watchdog script (watchdog_coagent.ps1)
- Added SSE transport to MCP server (--sse flag)
- Increased thread pool from 2 to 4 workers
- Fixed agent cursor overlay (layered window attributes)
- Added WinRT OCR diagnostics and fallback improvements
- Updated all version strings to v7.0
```

Then push:
```
git add -A && git commit -m "v7.0: Modular refactor + watchdog + SSE + fixes" && git tag v7.0 && git push && git push --tags
```

---

## EXECUTION ORDER (DO THIS)

1. Create `shared.py`
2. Create `routes_mouse.py`
3. Create `routes_ocr.py`
4. Create `routes_uia.py`
5. Create `routes_file.py`
6. Create `routes_media.py`
7. Create `routes_v63.py`
8. Rewrite `hermes_coagent.py` (~600 lines, imports from modules)
9. Fix `coagent_features.py` cursor overlay
10. Fix `_windows_ocr()` in routes_ocr.py
11. Update `computer_use_mcp.py` with SSE + --port
12. Change max_workers from 2 to 4 everywhere
13. Create `watchdog_coagent.ps1`
14. Update version strings everywhere
15. Write verification script `_verify_v70.ps1`
16. Run verification script
17. Kill old processes, launch CoAgent via schtasks
18. Verify with curl /ping
19. Commit and push with tag v7.0
20. Update SKILL.md on WSL side

## WARNING: DO NOT SKIP STEPS

You have 300 seconds. Go fast. The order above is designed so that the route-move steps are pure extract-and-delete — no logic changes — making them fastest first. Only after all routes are cleanly extracted do you do the improvements (fixes, watchdog, version bumps).

If you get close to timeout, at least complete steps 1-8 and 17-18 (the split and relaunch). The minor fixes can be done in a second pass.
