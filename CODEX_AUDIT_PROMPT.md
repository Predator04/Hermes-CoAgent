# CoAgent Code Audit & Optimization

You are performing a full code review of Hermes CoAgent v7.0. This is a Windows desktop automation server using Flask with auth, UIA, OCR, mouse/keyboard control, file ops, and MCP integration.

## Files to Review (in priority order)

1. **auth.py** — Security module. Token generation, persistence to .token file, Bearer auth decorator, and auth routes (/auth/token GET/POST, /auth/token/show GET, /auth/token/reset GET/POST).

2. **hermes_coagent.py** — Main entry point. Flask app, route registration, tray icon launch, singleton mutex, waitress/Flask server.

3. **shared.py** — Shared utilities. COAGENT_DIR, SERVER_PORT, logging, path safety, interactive task XML, JSON body parsing.

4. **routes_mouse.py** — Mouse/keyboard/chain/emergency endpoints.

5. **routes_ocr.py** — Screenshot capture, OCR, crop, describe endpoints.

6. **routes_uia.py** — UIA tree, SOM overlays, element finding.

7. **routes_file.py** — File ops, app launch, power management.

8. **routes_media.py** — Wallpaper, windows, clipboard, macros, scheduler, voice, tunnel.

9. **coagent_features.py** — Agent cursor overlay, element-indexed UIA, session recording, desktop stabilization.

10. **computer_use_mcp.py** — MCP server connecting to CoAgent.

11. **uia_engine.py** — UIA engine for Windows UI automation.

12. **tray_icon.py** — System tray with screenshot relay.

## What to Check

### Security
- Command injection vulnerabilities (all shell=True, os.system, subprocess with shell)
- Path traversal (user-supplied paths in file routes)
- Token leaks in error messages
- Missing auth on any routes that modify system state
- Secrets exposed in logs

### Correctness
- Auth routes work properly (verify token compare, global state management)
- Screenshot capture works (MSS/PIL fallbacks)
- UIA warmup at startup
- Mutex/Singleton pattern works
- Background input (copilot mode) vs foreground
- Error handling on all routes

### Performance
- Unnecessary file I/O in hot paths
- Repeated imports
- Thread safety issues
- Unbounded collections
- Slow exception handling patterns

### Code Quality
- Redundant code / dead code
- Unused imports
- Inconsistent error response format
- Missing input validation
- Hardcoded paths that should be relative
- Docstrings / comments that are wrong

### Potential Issues to Flag
- The `{prefi...}` string literal issue in auth.py (the system keeps mangling f-strings containing {prefix} and {suffix} — check if line 84 is correct)
- The `nul` file in the repo directory — seems like a PowerShell redirect artifact
- The `.token` file being committed to git (should be in .gitignore if not already)

## Output Format

Write your review to **CODEX_AUDIT_REPORT.md** in the CoAgent directory with these sections:

1. **Critical Issues** — bugs, security holes, data loss risks
2. **Performance Optimizations** — concrete before/after suggestions
3. **Code Quality** — dead code, redundancy, style
4. **Quick Wins** — < 5 minute fixes with high impact
5. **Summary** — overall health score (A-F), top 3 things to fix

Be specific: include file paths, line numbers, and exact code snippets for every finding. Prioritize security > correctness > performance > style.
