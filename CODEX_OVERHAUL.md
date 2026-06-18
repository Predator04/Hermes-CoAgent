You are Codex CLI running in the Hermes CoAgent repo at `C:\Users\Admin\Desktop\Hermes CoAgent\`.

Your mission: **Do a full, complete overhaul of this codebase.** Leave nothing untouched that needs fixing. Treat every finding in CODEX_AUDIT_REPORT.md as gospel, and find even more that the report missed.

## Step 1: Read Everything

Read every .py file in the repo. All of them. Build a complete mental model of:
- Every Flask route, its handler, its auth status
- Every subprocess/command execution
- Every file read/write with user-supplied paths
- Every TTS/voice/speech endpoint
- Every macro/mouse/keyboard chain
- Every scheduler/recording/cursor feature endpoint
- The auth system top to bottom
- The MCP server
- The UIA engine
- The tray icon relay
- The shared module
- The launch scripts (.bat, .ps1)

## Step 2: Fix ALL Security Issues

### Auth System
The auth system is BROKEN. Fix it completely:
1. `--token=KEY` does not trigger auth init (checks `"--token"` in argv but actual arg is `"--token=KEY"`)
2. `--allow-external` logs "Auth: enabled" even when auth didn't actually enable
3. The conditional import on line 29-43 of hermes_coagent.py means if auth.py fails to import, ALL routes become unprotected silently
4. Most routes in routes_ocr.py, routes_uia.py, routes_media.py have NO @require_auth decorator
5. `/auth/token/reset` requires no auth and rolls back token state
6. Make default-deny the standard: if auth is enabled, EVERY route should require a token EXCEPT explicitly allowlisted ones (/, /ping, /version, /health)

### Route Protection - Add @require_auth to ALL of these:
routes_ocr.py: /screen, /screen/jpeg, /screen/base64, /screen/fresh, /screen/diag, /ocr/find, /visual/find, /crop, /describe
routes_uia.py: /uia/tree, /uia/find/<name>, /uia/find/name/<name>, /uia/click, /uia/element/*, /som/* (every SOM route), /wait/ui
routes_media.py: /clipboard/get, /clipboard/set, /windows/activate, /windows/find, /wallpaper/set, /wallpaper/random, /scheduler/*, /macro/*, /voice/*, /launch/ai, /search/files, /cursor/*, /recording/*, /wait/*, /stabilize
routes_file.py: /power/* (sleep, restart, shutdown, hibernate)
routes_mouse.py: /emergency/stop, /emergency/resume
hermes_coagent.py: /logs

### TTS Command Injection
The TTS endpoint at routes_media.py builds PowerShell with user text interpolated:
```python
ps_script = f'''...$s.Speak(\"{text.replace('\"', '\"\"')}\")...'''
```
This is RCE. Fix it by writing text to a temp file and reading it from a static PowerShell script. Or use `-EncodedCommand`. Or just use the windows TTS via Python directly with win32com.client. The BEST fix: use `pyttsx3` or SAPI via ctypes.

### Macro Path Traversal
Macro names flow directly into filesystem paths with only `.json` appended. Fix:
- Validate names: `^[A-Za-z0-9_.-]{1,80}$`
- Resolve the path and verify it's under MACROS_DIR using `Path.resolve()`
- Protect /macro/save, /macro/run, /macro/delete with auth

### File Route Path Traversal
routes_file.py: check that resolved paths for file operations are under ALLOWED_ROOTS

### Emergency Routes
/mouse/emergency/stop and /mouse/emergency/resume must require auth

## Step 3: Fix All Performance Issues

1. **shared.py** has a `subprocess.run` to PowerShell at IMPORT TIME that can block for 5 seconds. Make it lazy (either cached after first call, or only run in routes that need it like /screen/diag)
2. **/logs endpoint** reads the ENTIRE log file (up to 5MB) then slices the last N lines. Use `deque` or read from the tail
3. **UIA engine** creates daemon threads per request with no cap. Add a threading.BoundedSemaphore or single-worker pattern
4. **OCR temp files** are not cleaned up on timeout/error paths (temp PS1 script is left behind)

## Step 4: Fix All Code Quality Issues

1. **routes_v63.py** is imported nowhere and contains duplicate routes that overlap routes_media.py. Either register it properly or delete it and absorb any unique routes into routes_media.py
2. **Stub feature endpoints**: /cursor/enable, /cursor/disable, /recording/start, /recording/stop in routes_media.py just return mock JSON. Wire them to coagent_features.py or remove them from /version feature list
3. **MCP --port not used**: computer_use_mcp.py parses --port but doesn't pass it to mcp.run()
4. **WinRT OCR fallback**: only catches ImportError, not AttributeError/TypeError from API mismatches
5. **auth.py line 84**: the `{prefi...}` f-string issue — if line 84 has `{prefi...` instead of `{pre}...{suf}`, fix it

## Step 5: Add to .gitignore

Add `.token`, `.token_*`, `nul`, `*.log`, `CODEX_FIX_PROMPT.md` to .gitignore if missing. Delete the `nul` file artifact if it exists in the repo.

## Step 6: Verify Every Change

After each file modification, run:
```python
import py_compile
py_compile.compile('path/to/file.py', doraise=True)
```

## Step 7: Show the Full Diff

At the end, run `git diff --stat && git diff` to show every change made. If files are untracked, include `git status --short`.

## Step 8: Generate Updated Audit Report

Write a new file called `CODEX_AUDIT_REPORT_v2.md` with final health score and all fixes applied.

## Rules
- Fix code in-place, read then write
- Do NOT add new dependencies (no pip install)
- Do NOT restructure the app — add guards, don't refactor logic flow
- If a fix is impossible without breaking the app, note it in the report and skip it
- Actually fix things — don't just describe what should be fixed
- You have 5 minutes max. Prioritize P0 > P1 > P2. If you run out of time, fix as many P0s as possible and report remaining items.
