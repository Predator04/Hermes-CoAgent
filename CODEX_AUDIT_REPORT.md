# Code Audit Report

## Summary

Overall verdict: Hermes CoAgent v7.3 is modular and the main route files parse cleanly, but the current secure-mode boundary is not safe for an external bind. The top priority is the auth exemption regression: routes that appear decorated with `@require_auth` are bypassed when their path matches `AUTH_EXEMPT_PREFIXES` or `AUTH_EXEMPT_PATHS`.

Top 3 priorities:

1. Fix auth exemptions and re-test a no-token route matrix. Current no-token checks returned `200` for `/screen`, `/screen/diag`, `/logs`, `/features`, `/history`, `/monitors`, `/stats`, `/cursor/status`, and `/recording/status` while the server is running with `--secure --allow-external`.
2. Retire the live `C:\tmp\screenshot_relay.py` process. It differs from the project relay, binds `0.0.0.0:9124`, and served a no-auth screenshot.
3. Wire the feature modules into the action path. Cursor overlay, macro recording, action history, SSE events, and session recording expose endpoints but are not consistently connected to mouse/key/action execution.

## Security Issues

### Critical: secure-mode auth bypass for sensitive route groups

Evidence:

- `hermes_coagent.py:39-44` skips route-level auth when `g._auth_passed` is set.
- `hermes_coagent.py:73-118` marks broad prefixes as exempt, including `/screen`, `/ocr`, `/visual`, `/crop`, `/describe`, `/uia`, `/som`, `/monitors`, `/stats`, `/history`, and `/events`.
- `hermes_coagent.py:120-128` sets `g._auth_passed = True` for exempt paths.
- Live no-token checks returned `200` for sensitive endpoints: `/screen/diag`, `/features`, `/logs`, `/history`, `/cursor/status`, `/recording/status`, `/monitors`, and `/stats`.
- Live no-token `/screen` returned `200 image/jpeg`, `323361` bytes, `X-Capture-Method=tray-relay`.

Impact: with `--allow-external`, unauthenticated network clients can read screen data, UI diagnostics, logs, state, feature status, and possibly UIA/SOM data. This is a direct desktop data exposure.

Fix:

- Narrow `AUTH_EXEMPT_PREFIXES` to static assets only.
- Keep only truly public health/documentation paths in `AUTH_EXEMPT_PATHS`, for example `/`, `/ping`, `/health`, `/version`, and `/favicon.ico`.
- Do not use `g._auth_passed = True` to mean "route is exempt". Use a separate marker such as `g._auth_exempt = True`, or remove route-level decorators from public routes and let `@require_auth` always enforce auth when present.
- Add an automated route matrix test that starts secure mode and asserts no-token `401/403` for screenshots, UIA/SOM, logs, clipboard, macro, scheduler, file, power, and control routes.

### Critical: live screenshot relay is outside the repo and exposed on all interfaces

Evidence:

- Live process: `pythonw.exe C:\tmp\screenshot_relay.py 9124`.
- `Get-NetTCPConnection` showed listeners on `0.0.0.0:9123` and `0.0.0.0:9124`.
- The project copy binds localhost at `screenshot_relay.py:99`, but the live `C:\tmp\screenshot_relay.py` binds `0.0.0.0` at line 96.
- Project and live relay hashes differ:
  - project `screenshot_relay.py`: `6972141A14B754AA78D89EAC9B419682A101D70A516ED805F1870E51460A65AC`
  - live `C:\tmp\screenshot_relay.py`: `C9D5FD113A7BEA4448019A7C170AC72BD1CC417638403B0F00FA7CD86B948100`
- No-token `http://127.0.0.1:9124/screen?format=jpeg` returned `200 image/jpeg`, `323361` bytes.

Impact: a stale or unmanaged relay can expose screenshots even if the Flask app auth is fixed.

Fix:

- Stop and remove the `C:\tmp\screenshot_relay.py` runtime path.
- Ensure launch scripts kill stale `screenshot_relay.py` and `tray_icon.py` processes by command line, not only `hermes_coagent`.
- Bind the relay to `127.0.0.1` only unless it has its own auth.
- Add a startup assertion that the relay process path matches the project directory.

### High: `/auth/token` leaks auth metadata without authentication

Evidence:

- `auth.py:113-124` returns `auth`, `token_preview`, `saved`, and `token_path` without requiring auth.
- Live no-token check returned `STATUS=200` and confirmed `TOKEN_PREVIEW_PRESENT=True` and `TOKEN_PATH_PRESENT=True`.

Impact: the endpoint does not leak the full token, but it gives unauthenticated clients token metadata and a local token file path. On an external bind, that is avoidable reconnaissance.

Fix: require auth for `/auth/token` when auth is enabled, or return only `{"auth": true}` to unauthenticated callers.

### Medium: recording output path is not sanitized

Evidence:

- `routes_v63.py:82-87` exposes `/recording/start`.
- `coagent_features.py:415-426` accepts `output_dir` directly as `Path(output_dir)`, creates session directories, and prunes old `session_*` directories under that path.

Impact: authenticated callers can write recording metadata and screenshots outside the project or expected user profile. If a token is exposed, this becomes arbitrary directory creation plus bounded deletion of matching `session_*` folders.

Fix: run `output_dir` through the same resolved-root sanitizer used by file routes, or restrict recordings to a configured recordings root.

### Medium: implementation details are exposed in error responses

Evidence:

- `hermes_coagent.py:236-240` returns exception type and first 200 characters of exception detail.
- Multiple routes return `{"error": str(e)}`, for example `routes_file.py:28-29`, `routes_file.py:47-48`, `routes_ocr.py:439-440`, and `routes_uia.py:167-168`.

Impact: with the auth bypass, unauthenticated callers can use error strings for host/path/library reconnaissance. Even after auth is fixed, external mode should avoid verbose internals by default.

Fix: return generic client-safe errors by default and keep detailed tracebacks in local logs or a debug-only endpoint.

### Medium: exact exempt paths skip rate limiting

Evidence:

- `hermes_coagent.py:211-217` skips rate limiting for exact `AUTH_EXEMPT_PATHS` and `/auth/`.
- Current exact exemptions include `/screen`, `/screen/base64`, `/screen/fresh`, `/screen/probe`, `/logs`, `/history`, `/features`, `/cursor/status`, `/recording/status`, and `/som/cache/clear` at `hermes_coagent.py:88-113`.

Impact: several exposed read-heavy endpoints are also unthrottled. Screenshot and log routes are especially risky.

Fix: apply rate limiting before auth exemption, or only skip rate limiting for very cheap health routes.

## Performance Issues

### SOM cache variables are declared but not used

Evidence:

- `routes_uia.py:24-27` declares `_som_cache`, `_som_cache_ts`, and `_SOM_CACHE_TTL`.
- `routes_uia.py:175-180` clears the cache.
- `routes_uia.py:136-168` recomputes the screenshot and UIA snapshot every time and never reads the cache.

Impact: repeated SOM calls pay full screenshot plus UIA traversal cost even when the screen is unchanged.

Fix: either implement cache lookup keyed by screenshot hash and UIA window signature, or remove the dead cache state to avoid false confidence.

### UIA can become permanently disabled after one failed snapshot

Evidence:

- `uia_engine.py:212-218` returns early when `UIA_READY` is false.
- `uia_engine.py:281-287` sets `UIA_READY = False` when a snapshot does not succeed.

Impact: a transient timeout or busy desktop can force all future UIA calls to return "UIA not available" until process restart.

Fix: treat snapshot failure as transient. Track consecutive failures, add a cooldown, and allow future reinitialization attempts.

### Blocking OCR, TTS, screenshot, and UIA work runs in request threads

Evidence:

- `routes_ocr.py:242-244` runs PowerShell OCR with a 30 second timeout.
- `routes_media.py:206-208` runs PowerShell TTS with a 30 second timeout.
- `routes_uia.py:136-168` performs screenshot decoding and UIA traversal inline.
- Waitress runs with 8 threads at `hermes_coagent.py:496`.

Impact: a few slow OCR/TTS/UIA requests can occupy most request capacity.

Fix: push long operations into a worker queue with job IDs, cancellation, and progress endpoints.

### Screenshot fallback is currently broken

Evidence:

- Live no-token `/screen/probe` returned `METHOD=tray-relay`, `RELAY_AVAILABLE=True`, `RELAY_BYTES=323361`, `LOCAL_AVAILABLE=False`, `LOCAL_BYTES=0`.
- Live no-token `/screen/base64` and `/screen/jpeg` returned HTTP 500.

Impact: raw/base64 screenshot tools fail unless the relay path is used. The system is operational for `/screen`, but not for MCP tools that call `/screen/base64`.

Fix: make `/screen/base64` use the tray relay as a fallback source, or repair local MSS/PIL capture for the server process.

### Session recording cleanup has no byte quota

Evidence:

- `coagent_features.py:384-426` keeps only 10 session directories by count.
- `coagent_features.py:470-484` can save a screenshot per recorded action.
- Current `$env:USERPROFILE\Desktop\CoAgent_Recordings` was missing during the audit, so no live disk usage was observed.

Impact: a small number of long recording sessions can still consume significant disk.

Fix: enforce a max total byte cap, max turns per session, and optional screenshot compression/quality settings.

## Feature Gaps

### v6.3 feature routes exist, but action integration is incomplete

Evidence:

- `coagent_features.py:447-492` defines `record_action()`.
- `coagent_features.py:101-145` defines cursor display and animation helpers.
- Search found no calls to `record_action()`, `animate_cursor_to()`, or `show_cursor_at()` from `routes_mouse.py` or `hermes_coagent.py`.

Priority: high.

Fix: route all action execution through a single action bus that records history, emits SSE, triggers cursor visualization, and writes session recording turns.

### Cursor overlay likely does not render a visible marker

Evidence:

- `coagent_features.py:49-67` creates a `STATIC` layered window and sets alpha.
- `coagent_features.py:93-99` stores color and size, but color is not used for drawing.
- `coagent_features.py:101-115` only moves/resizes the window with `SetWindowPos`; no paint handler, bitmap, text, or region is applied.

Priority: high for UX.

Fix: implement a real painted layered window, use UpdateLayeredWindow, or reuse the accepted pulse popup path with a visible shape.

### Window management is minimal and dashboard calls missing endpoints

Evidence:

- Implemented routes are list and activate only at `routes_media.py:54-97`.
- `routes_media.py:149-155` `/monitors/layout` only logs and echoes the layout.
- `dashboard.html:906-908` calls `POST /minimize`, but no such Flask route was found.

Priority: medium.

Fix: add minimize/maximize/restore/close/tile routes, and align dashboard buttons to real endpoints.

### Dashboard route names and response shapes drifted

Evidence:

- Dashboard calls `/mouse/doubleclick` and `/mouse/rightclick` at `dashboard.html:637-638`.
- Actual routes are `/mouse/dblclick` and `/mouse/rclick` at `routes_mouse.py:113-125`.
- Dashboard file list expects `d.items` at `dashboard.html:709-714`; route returns `entries` at `routes_file.py:19-27`.
- Dashboard macro run expects `executed` and `total` at `dashboard.html:870-874`; route returns `count` at `routes_media.py:312-318`.

Priority: medium.

Fix: add backward-compatible aliases or update the dashboard to current route names and JSON shapes.

### Macro recording, replay, history, and SSE are not wired

Evidence:

- `routes_media.py:9-15` defines `_action_history`, `_recording`, and `_recorded_actions`.
- `routes_media.py:320-332` toggles macro recording but no code appends executed actions to `_recorded_actions`.
- `routes_media.py:348-357` replays `_action_history`, but no route appends to `_action_history`.
- `shared.py:184-213` defines SSE client management, and `routes_media.py:453-456` exposes `/events`, but search found no `sse_broadcast()` call in action execution.

Priority: high.

Fix: every successful `/act`, `/chain`, mouse, key, macro, and scheduler execution should append history and emit SSE events.

### Scheduler and tunnel endpoints are placeholders

Evidence:

- `routes_media.py:261-271` `/scheduler/run` logs and returns `executed`, but does not execute the stored action.
- `routes_media.py:369-385` tunnel start/stop/status only returns static status and never starts a tunnel.

Priority: medium.

Fix: implement actual scheduler execution using the same action bus, and either implement tunnel lifecycle management or mark tunnel endpoints as unavailable.

### Multi-monitor and process management are shallow

Evidence:

- `routes_media.py:140-147` `/monitors` returns only a single `pyautogui.size()` display and `count: 1`.
- There are power routes and app launch routes, but no process list/kill/details endpoints.
- No notification area monitoring or network/connectivity monitoring routes were found.

Priority: medium.

Fix: add monitor enumeration via Windows APIs, process inventory/control routes, notification-area inspection, and connectivity diagnostics.

### MCP file operations are incomplete

Evidence:

- REST file routes exist in `routes_file.py:10-88`.
- MCP exposes `launch_app()` at `computer_use_mcp.py:637-641`, but no MCP tools for file list/read/write/delete/upload/download were found.

Priority: medium.

Fix: add MCP tools that proxy the existing file routes, with size limits and explicit return-shape tests.

## Code Quality

### Dead or misleading state

- `routes_uia.py:24-27`: SOM cache state exists but is not read.
- `routes_mouse.py:93-96`: `_limit_arg()` is unused and reads from `flask.g` instead of request args/body.
- `coagent_features.py:33`: `_CURSOR_WINDOW` is unused.
- `coagent_features.py:44-46`: fade/dwell constants are unused.
- `routes_media.py:9-15`: action history and macro recording state are not populated by action execution.

### Documentation drift

- `ROUTE_MAP.py:26-126` marks many sensitive routes as `No` auth.
- `CODEX_REVIEW.md:14-21` says the broad auth exemption list was fixed, but current `hermes_coagent.py:73-113` contains broad exemptions again.
- `hermes_coagent_audit_prompt.md` says v7.3a, while `shared.py:13-14` reports `VERSION = "7.3"` and `BUILD = "2026-06-18"`.

### Error response consistency

- Global Flask errors are JSON at `hermes_coagent.py:220-240`.
- `/logs` returns HTML at `hermes_coagent.py:422-434`.
- The project relay sends `text/plain` for handler exceptions at `screenshot_relay.py:79-80`.

### Test coverage gaps

Missing or not observed:

- Secure-mode no-token route matrix.
- Dashboard route/schema contract tests.
- Screenshot relay source-path and bind-address tests.
- UIA recovery after timeout.
- File path sanitizer tests for symlinks, roots, and deletion boundaries.
- Macro/session recording integration tests.
- SSE event emission tests.

## Recommendations

1. Fix the auth gate and exemption list. Estimated effort: 1-2 hours including a no-token route matrix test.
2. Stop the stale `C:\tmp` relay and enforce project-local, localhost-only relay startup. Estimated effort: 1-2 hours.
3. Fix `/screen/base64` and `/screen/jpeg` to use the relay fallback or repair local capture. Estimated effort: 2-4 hours.
4. Remove unauthenticated `/auth/token` metadata leakage and tighten `.token` file ACLs. Estimated effort: 1 hour.
5. Wire a central action bus for history, macro recording, session recording, cursor overlay, and SSE events. Estimated effort: 0.5-1 day.
6. Align dashboard routes and JSON expectations with Flask routes. Estimated effort: 2-4 hours.
7. Implement real scheduler/tunnel/window-management behavior or mark placeholders explicitly unavailable. Estimated effort: 1-2 days depending on scope.
8. Add regression tests for auth, route schemas, UIA recovery, screenshot capture, and file path sanitization. Estimated effort: 1-2 days.

## Evidence

Audit inputs:

- Read `hermes_coagent_audit_prompt.md` and audited the requested files: `hermes_coagent.py`, `routes_ocr.py`, `uia_engine.py`, `coagent_features.py`, `shared.py`, `computer_use_mcp.py`, `tray_icon.py`, and `screenshot_relay.py`.
- Also read route modules needed by the current modular app: `routes_mouse.py`, `routes_uia.py`, `routes_file.py`, `routes_media.py`, `routes_v63.py`, and `auth.py`.

Static checks:

- AST parse passed for `hermes_coagent.py`, all route modules, `shared.py`, `computer_use_mcp.py`, `coagent_features.py`, `tray_icon.py`, `screenshot_relay.py`, `uia_engine.py`, and `auth.py`.
- `rg "shell\s*=\s*True"` found no executable `shell=True` usage; only `ROUTE_MAP.py` documentation mentioned "No shell=True".
- `git diff --check` reported only line-ending warnings for existing dirty files.

Live runtime:

- Running CoAgent process: `pythonw.exe "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" --secure --allow-external`.
- Running relay process: `pythonw.exe C:\tmp\screenshot_relay.py 9124`.
- Listeners observed: `0.0.0.0:9123` owned by CoAgent PID `29380`; `0.0.0.0:9124` owned by relay PID `23744`.

No-token endpoint checks:

```text
/ping STATUS=200 TYPE=application/json LEN=62
/version STATUS=200 TYPE=application/json LEN=624
/file/list STATUS=401 TYPE=application/json
/screen/diag STATUS=200 TYPE=application/json LEN=82
/uia/diag STATUS=200 TYPE=application/json LEN=26
/features STATUS=200 TYPE=application/json LEN=90
/logs STATUS=200 TYPE=text/html; charset=utf-8 LEN=5485
/history STATUS=200 TYPE=application/json LEN=25
/cursor/status STATUS=200 TYPE=application/json LEN=44
/recording/status STATUS=200 TYPE=application/json LEN=52
/monitors STATUS=200 TYPE=application/json LEN=38
/stats STATUS=200 TYPE=application/json LEN=39
```

Screenshot checks:

```text
coagent_screen STATUS=200 TYPE=image/jpeg LEN=323361 METHOD=tray-relay RELAY_LATENCY=216.7
screen_probe STATUS=200 METHOD=tray-relay RELAY_AVAILABLE=True RELAY_BYTES=323361 LOCAL_AVAILABLE=False LOCAL_BYTES=0
relay_health STATUS=200 BODY={"status":"ok","session":1}
relay_screen_jpeg STATUS=200 TYPE=image/jpeg LEN=323361
/screen/base64 STATUS=500
/screen/jpeg STATUS=500
```

Auth metadata check:

```text
/auth/token STATUS=200 KEYS=auth,saved,token_path,token_preview AUTH=True TOKEN_PREVIEW_PRESENT=True TOKEN_PATH_PRESENT=True
```

Source/runtime drift:

```text
project screenshot_relay.py SHA256 6972141A14B754AA78D89EAC9B419682A101D70A516ED805F1870E51460A65AC
live C:\tmp\screenshot_relay.py SHA256 C9D5FD113A7BEA4448019A7C170AC72BD1CC417638403B0F00FA7CD86B948100
```

Log observations:

- `tray_icon.log` contains repeated `schtasks create: ERROR: Access is denied.`
- `tray_icon.log` contains repeated `[WinError 10048] Only one usage of each socket address...` for the screenshot server.
- `tray_icon.log` contains `import error: No module named 'PIL'` on 2026-06-18.
- Current project `screenshots` directory had `screenshots_count=0`.
- `$env:USERPROFILE\Desktop\CoAgent_Recordings` was not present during the audit.

