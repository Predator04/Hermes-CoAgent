# Codex: Test Everything in CoAgent v8.1

## Context
This is the Hermes CoAgent project at `C:\Users\Admin\Desktop\Hermes CoAgent\`. It's a Flask-based desktop automation server (port 9123) with 48+ route modules. Current version is v8.1.

## What I Need

### 1. Run existing tests and fix any failures
```
cd C:\Users\Admin\Desktop\Hermes CoAgent
python -m pytest tests/ -v --tb=short 2>&1
```
If any tests fail, fix the code.

### 2. Create comprehensive tests for the v8.1 features

The following NEW code was added by Codex in v8.1. Test EACH of them:

#### a) **`shared.py`** — Test VERSION, BUILD, SSE helper functions
- `_json_frame(event, data)` returns `f"event: {event}\ndata: {json.dumps(data)}\n\n"` 
- `_sse_response(events)` returns a Flask Response with `text/event-stream` content type
- `_missing_field(payload, field)` returns a 400 JSON when field is missing
- `_json_body(data, status=200)` returns a Flask response with JSON content type

#### b) **`routes_mcp.py`** — MCP server mode (SSE + stdio transport)
- Test that all expected tools are discovered (357 tools in ROUTE_MAP)
- Test `GET /mcp/sse` returns `text/event-stream`
- Test `POST /mcp/message` returns proper JSON-RPC
- Test that auth is enforced on MCP routes

#### c) **`routes_memory.py`** — Cross-session memory
- Test `POST /memory/store` stores key-value pairs
- Test `GET /memory/recall/<key>` retrieves stored values
- Test `GET /memory/search?q=...` searches across stored keys/values
- Test `POST /memory/forget/<key>` removes entries
- Test `GET /memory/stats` returns memory usage stats

#### d) **`routes_reminders.py`** — Timed reminders
- Test `POST /reminders/create` schedules a reminder
- Test `GET /reminders/list` shows active reminders
- Test `POST /reminders/cancel/<id>` cancels a reminder
- Test `GET /reminders/stats` returns reminder status

#### e) **`routes_hud.py`** — Desktop HUD overlay
- Test `POST /hud/show` displays overlay (may fail if no desktop, handle gracefully)
- Test `POST /hud/hide` hides overlay
- Test `POST /hud/text` updates overlay text
- Test `POST /hud/progress` updates progress bar
- Test `GET /hud/status` returns HUD status

#### f) **`screenshot_relay.py`** — The screenshot relay
- Test that the relay starts and responds on port 9124
- Test `GET /health` returns `{"status": "ok"}`
- Test `GET /screenshot` returns JPEG bytes
- Test `GET /screen` also works
- Test `GET /nonexistent` returns 404

#### g) **`routes_copilot_enhanced.py`** — Goal Runner enhancements
- Test `GET /copilot/status` returns current state
- Test `POST /copilot/goal` starts a new goal
- Test `POST /copilot/stop` stops a running goal
- Test `GET /copilot/timeline` returns goal timeline
- Test `GET /copilot/progress` returns goal progress percentage
- Test SSE endpoint for real-time goal updates
- Test screenshot verification works and doesn't break non-screenshot goals

#### h) **`routes_uia.py`** — Hybrid UIA+Vision
- Test `GET /uia/tree` returns UIA tree
- Test `POST /uia/click` by element name
- Test `POST /uia/type` types text
- Test `POST /uia/find` finds element
- Test `POST /uia/ocr` returns OCR text
- Test vision fallback works when UIA misses

#### i) **`routes_recipes.py`** — Recipe verification
- Test `GET /recipes/list` returns available recipes
- Test `POST /recipes/run` executes a recipe
- Test `GET /recipes/status/<id>` returns recipe status
- Test recipe verification (each step verified before proceeding)

#### j) **`launch_all.ps1`** — Launch script
- Test syntax parsing: `powershell -NoProfile -Command "Get-Content launch_all.ps1 | Out-String | Invoke-Expression"` should parse cleanly
- Test the relay auto-start path (pid file check, port check)

#### k) **Single-instance protection** (Codex just added this)
- Test that `coagent.pid` is created when server starts
- Test that port check prevents duplicate launch
- Test that Windows named mutex exists
- Test that cleanup happens on exit

#### l) **`tray_icon.py`** — Tray icon
- Test that tray icon starts without errors
- Test health check loop works
- Test all menu items (Open Dashboard, ⚙️ Settings, Check Health, Restart Server, Exit)

### 3. Test edge cases
- All routes return proper error codes (400, 401, 404, 413, 500)
- Empty/null input handling
- Unicode text handling
- Session 0 vs Session 1 awareness (skip tests that need real desktop)
- Token/auth is properly enforced on protected routes

### 4. Import pattern (critical — tests MUST use this)
```python
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

### 5. Do NOT commit or tag
Just write tests, run them, fix failures.

## Files to create/modify
- `tests/test_shared.py` — shared.py tests
- `tests/test_mcp.py` — MCP routes tests
- `tests/test_memory.py` — Memory routes tests  
- `tests/test_reminders.py` — Reminder routes tests
- `tests/test_hud.py` — HUD routes tests
- `tests/test_screenshot_relay.py` — Screenshot relay tests
- `tests/test_copilot_enhanced.py` — Goal runner tests
- `tests/test_uia.py` — UIA+Vision tests
- `tests/test_recipes.py` — Recipe tests
- `tests/test_launch.py` — Launch script tests
- `tests/test_tray.py` — Tray icon tests

Keep tests focused on unit tests for the route handlers with `app.test_client()`. Skip tests that need real desktop access or running servers — mock those.

## Verify
Final command: `python -m pytest tests/ -v --tb=short 2>&1`
All tests must pass.
