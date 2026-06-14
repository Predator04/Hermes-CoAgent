# Hermes CoAgent — Codex Audit & Fix Instructions

## Project Overview

Two Python files in `C:\Users\Admin\Desktop\Hermes CoAgent\`:

1. **`hermes_coagent.py`** (1,077 lines) — Flask server on port 9123. Desktop control web dashboard + MCP mode + OCR + visual search + TTS + macros + file explorer + Cloudflare tunnel.
2. **`coagent_tray.py`** (571 lines) — PySide6 system tray app (icon by the clock). Server control, stats, notifications, clipboard history, pairing QR, quick actions, auto-update, log viewer.

## What Codex Must Do

Audit both files for bugs, crashes, and improvements. Fix every issue found. Then verify the tray app starts without crashing and the server responds to all key endpoints.

## Known Issues to Fix

### 1. Tray crash on startup (FIXED) — `coagent_tray.py`
- **ROOT CAUSE**: `_clip_history` initialized at line 321 but `_build_menu()` called at line 316 before it exists → `AttributeError: 'CoAgentTray' object has no attribute '_clip_history'`.
- **FIX APPLIED**: Moved `self._clip_history = []` and `self._last_clip = ""` before `self._build_menu()`. ✔️
- **VERIFY**: Run the tray from command line: `python coagent_tray.py` — it should stay running, not crash.

### 2. `_poll_notifications` endpoint mismatch — `coagent_tray.py`
- **ISSUE**: `_poll_notifications()` calls `GET /history?limit=1` and checks `len(r.get("actions", []))` against `_last_notif_count`. But the `/history` endpoint might not return an `actions` key with the correct structure.
- **VERIFY**: Check the actual `/history` route in `hermes_coagent.py` — confirm what key and shape it returns. If it returns something other than `{"actions": [...]}`, fix the tray to match.

### 3. `_build_clip_menu` lambda late-binding bug — `coagent_tray.py` lines 453-457
- **ISSUE**: The clipboard menu uses `lambda checked, t=entry` which captures `entry` by value (correct). But this is a `for entry in self._clip_history[-20:]` loop — the default arg pattern is correct for capturing by value in a loop. No bug here, but verify the entire method.

### 4. Server `/history` route — `hermes_coagent.py`
- **ISSUE**: The tray calls `GET /history?limit=1` — need to confirm this route exists and returns `{"actions": [...]}`. Search the server file for `@app.route("/history"` — if it doesn't exist, the tray notification polling will silently fail.

### 5. `_execute_action_wrapper` recursion risk — `hermes_coagent.py` lines 678-685
- **ISSUE**: `_execute_action_orig = _execute_action` at line 679, then `_execute_action = _execute_action_wrapper` at line 685. The wrapper calls `_execute_action_orig(action)`. But what happens if any route handler imports or references `_execute_action` **after** this wrapper is assigned? The module-level name now points to the wrapper. If any function defined **above** line 678 calls `_execute_action`, the original is safe (Python captured the original at def time). But if the MCP handler lambdas at lines 202-230 capture `_execute_action` from the module scope, they'll get the WRAPPER → double-send to SSE/logs + action_history appended twice.
- **FIX**: Change the wrapper to NOT call `state.action_history.append` (the original already does at line 98). The wrapper should only _sse_broadcast + _log. The wrapper as written correctly does NOT call append — it's safe. Verify this.

### 6. `_execute_action` thread safety — `hermes_coagent.py` line 98
- **ISSUE**: `state.action_history.append(...)` happens AFTER the lock is released (the `finally` block at line 96-97 only handles `state.last_action_time`). The `action_history.append` is technically outside the `with state.input_lock:` block. In theory, two concurrent API calls could interleave the append. This is unlikely to cause visible problems but it's a minor race.
- **FIX (optional)**: Move the append inside the `try` block before `finally`.

### 7. `/events` SSE may hang on disconnect — `hermes_coagent.py` lines 612-630
- **ISSUE**: The SSE generator uses `GeneratorExit` to clean up. Flask's dev server handles this, but in production (Waitress/Gunicorn) it might not. Verify the dead client removal works correctly.
- **FIX (optional)**: Add `@app.after_request` to clean up on connection close. Or wrap the generator in a context manager.

### 8. Missing `if __name__ == "__main__"` guard — `coagent_tray.py`
- **ISSUE**: Line 569-570 runs `CoAgentTray()` at module level inside `if __name__ == "__main__"`. ✔️ This is correct. But if someone imports the file accidentally, it won't crash. Verify.

### 9. File explorer `.gitignore` — not a bug but verify
- **CHECK**: The `.gitignore` should exclude `screenshots/`, `macros/`, `tunnel.log`, `tray_config.json`, `__pycache__/`, `*.pyc`. Verify the existing `.gitignore` covers these.

### 10. Tray config persistence — `tray_config.json`
- **ISSUE**: The `Config` class catches ALL exceptions silently (`except: pass`) during load. If the JSON is corrupted, settings silently reset to defaults. This is acceptable but the save operation writes atomically — verify.

## Verification Steps

After fixing all issues:

```powershell
# 1. Syntax check
python -c "import py_compile; py_compile.compile(r'C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py', doraise=True); print('server OK')"
python -c "import py_compile; py_compile.compile(r'C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py', doraise=True); print('tray OK')"

# 2. Start server on port 9123
cd "C:\Users\Admin\Desktop\Hermes CoAgent"
start /B python hermes_coagent.py 9123 > server.log 2>&1
timeout /t 3

# 3. Test endpoints
curl -s http://localhost:9123/ping
curl -s http://localhost:9123/stats
curl -s http://localhost:9123/logs
curl -s http://localhost:9123/history

# 4. Kill test server
taskkill /f /im python.exe

# 5. Launch tray and verify it stays alive for 5 seconds
start /B python coagent_tray.py > tray.log 2>&1
timeout /t 3
tasklist /fi "imagename eq python.exe"
```

## Code Style Rules

- **No Chinese or Unicode artifacts** in any file — Windows console can't display them.
- **No async/await** — everything is synchronous thread-pool.
- **No external network calls** except: `/tunnel/start` (Cloudflare) and `/app/run` (user commands).
- **All path strings**: use raw strings or escaped backslashes for Windows compatibility.
- All error handling: use bare `except:` (not `except Exception:`) ONLY at the outermost catch for user-facing APIs. Internal functions should catch specific exceptions.
- **No `print()` to stdout** in the server (it conflicts with MCP mode). Use `_log()` instead.
- **Tray app**: must launch from VBS wrapper, no cmd window visible.

## Quick Actions Format (config example)

```json
{
  "quick_actions": [
    {"name": "Open Chrome", "command": "start chrome"},
    {"name": "Take Screenshot", "command": "python screenshot.py"}
  ]
}
```

## Commit After Fixes

```powershell
cd "C:\Users\Admin\Desktop\Hermes CoAgent"
git add -A
git commit -m "v3.1.1 — Codex audit fixes: tray init ordering, notification polling, thread safety"
git push
```
