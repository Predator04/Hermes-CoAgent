# CoAgent v7.12 — BUILD ALL 6 MAJOR FEATURES

C:\Users\Admin\Desktop\Hermes CoAgent\

Build ALL 6 features below. Each gets its own file. Then integrate into hermes_coagent.py.

---

## FEATURE 1: AI Copilot (Full multi-step automation) — routes_copilot_enhanced.py

Upgrade the existing `/copilot` endpoint. Keep the original routes_copilot.py, add a new file for advanced AI chaining.

- `POST /copilot/goal` — Takes a natural language goal, breaks it into steps, executes them
  Body: {goal: "Open Telegram, search for William, send message 'hello'", max_steps: 10}
  Returns: {goal, steps: [{action, status, result}], completed: N, failed: N, duration_seconds: N}
  
- `GET /copilot/goal/{id}` — Returns status of a running goal
- `POST /copilot/stop/{id}` — Stops a running goal mid-execution

How it works:
1. Accept a natural language goal
2. Use the Agent Gateway (POST /agent/exec internally at 127.0.0.1:9123) to ask Codex to decompose:
   "Break this goal into step-by-step actions using available CoAgent API endpoints."
   Codex returns a JSON list of steps like:
   ```json
   [{"action": "launch", "params": {"query": "telegram"}},
    {"action": "wait", "params": {"seconds": 3}},
    {"action": "ocr_find", "params": {"text": "William"}},
    {"action": "click", "params": {"x": "$prev.x", "y": "$prev.y"}}]
   ```
3. Execute each step by calling CoAgent endpoints on localhost:9123
4. Track progress, handle errors (retry failed steps once), report results

Use internal HTTP calls to localhost:9123 (like routes_finder.py does) with the .token file.
Store active goals in memory dict with threading lock.
Max 3 concurrent goals.

Write to: routes_copilot_enhanced.py
Blueprint: "copilot_enhanced"
Auth: all routes require auth

---

## FEATURE 2: Web Dashboard Overhaul — dashboard.html inline rewrite

Rewrite dashboard.html completely. It's an HTML+JS single page app.

Requirements:
- **Dark theme** with modern UI (gradient headers, card layouts, smooth animations)
- **Live desktop stream** — embed the /screen/jpeg feed with auto-refresh (same as routes_webrtc.py's frame loop)
- **Control panel** — click on the live screen to send mouse clicks, drag to select regions
- **Command bar** — text input at the top that sends to /agent/exec (Codex) and shows output below
- **Keyboard input** — a text field to type text on the remote desktop
- **Undo button** — one-click /undo/last
- **GIF recorder controls** — Start/Stop recording with status indicator
- **File browser** — list files from /file/list, upload via drag-drop
- **Metrics panel** — real-time request count and memory from /metrics
- **Dashboard panels** organized in a tab/accordion layout:
  - 🖥️ **Desktop** — live screen + click controls
  - 🤖 **AI Copilot** — goal input + step results
  - 🎬 **Recorder** — GIF recording controls
  - 📁 **Files** — file browser + upload
  - 📊 **Metrics** — live graphs
  - ⚙️ **Settings** — Telegram config, webhooks, update check

- All API calls use the Bearer token from sessionStorage (already set by existing auth flow)
- CSS should be inline in the HTML file (no external deps except for any chart library via CDN)
- For the metrics graph, use Chart.js from CDN (cdn.jsdelivr.net/npm/chart.js)
- Responsive design — works on desktop and mobile
- Icons: use Unicode emoji (no icon library needed)
- Error handling: if an API call fails, show a toast notification

This should be a SINGLE self-contained HTML file. No separate CSS or JS files.
Read the EXISTING dashboard.html to understand the auth flow (token in sessionStorage), then rewrite completely.

Write to: dashboard.html (OVERWRITE existing)

---

## FEATURE 3: Scheduled Recipes — routes_recipes.py

Save and run multi-step automation recipes on schedules.

- `POST /recipes/create`
  Body: {name: "Morning Check", steps: [
           {action: "launch", params: {query: "outlook"}},
           {action: "wait", params: {seconds: 5}},
           {action: "telegram_send", params: {message: "Outlook opened"}}
         ], schedule: "0 9 * * *", enabled: true}
  Returns: {recipe_id, name, schedule, steps: N}

- `GET /recipes/list` — Returns all saved recipes
- `GET /recipes/{id}` — Returns a specific recipe
- `POST /recipes/run/{id}` — Execute a recipe immediately
- `POST /recipes/{id}` — Update a recipe (body: same as create)
- `DELETE /recipes/{id}` — Delete a recipe
- `POST /recipes/toggle/{id}` — Enable/disable a recipe
- `GET /recipes/logs/{id}` — Show execution history for a recipe

How it works:
- Recipes stored in COAGENT_DIR / "recipes.json" as a JSON file (persistent across restarts)
- Steps execute sequentially (same as copilot execution model)
- Scheduling: use a background thread that checks every 30s if any enabled recipe's cron expression matches the current time. Use `croniter` Python library (pip install croniter — make it optional, fallback to simple interval if not installed)
- If croniter not available, support simple schedules: "every X minutes", "hourly", "daily at HH:MM"
- Execution logs stored in memory (last 20 runs per recipe)
- Each step result captured: {step_index, action, status, result, duration}

Execution engine (shared with copilot):
```python
def _execute_steps(steps, timeout=300):
    """Execute a list of steps via CoAgent internal API calls."""
    results = []
    token_file = COAGENT_DIR / ".token"
    token = token_file.read_text().strip() if token_file.exists() else ""
    base = "http://127.0.0.1:9123"
    
    for i, step in enumerate(steps):
        action = step.get("action", "")
        params = step.get("params", {})
        start = time.time()
        try:
            if action == "wait":
                time.sleep(params.get("seconds", 1))
                result = {"status": "ok", "slept": params.get("seconds", 1)}
            elif action == "launch":
                # POST /process/start
                result = _coagent_post("/process/start", {"path": params.get("query")})
            elif action == "click":
                result = _coagent_post("/mouse/click", params)
            elif action == "type":
                result = _coagent_post("/key/type", params)
            elif action == "ocr_find":
                result = _coagent_post("/ocr/find", params)
            elif action == "telegram_send":
                result = _coagent_post("/telegram/send", params)
            elif action == "screenshot":
                result = _coagent_post("/screen/base64", {})
            elif action == "finder_click":
                result = _coagent_post("/finder/click", params)
            elif action == "finder_type":
                result = _coagent_post("/finder/type", params)
            else:
                result = {"error": f"Unknown action: {action}"}
            results.append({"step": i, "action": action, "status": "ok", "result": result, "duration": time.time()-start})
        except Exception as e:
            results.append({"step": i, "action": action, "status": "error", "error": str(e), "duration": time.time()-start})
            break  # Stop on failure
    return results
```

Helper `_coagent_post(path, data)` — same pattern as routes_finder.py.

Write to: routes_recipes.py
Blueprint: "recipes"
Auth: all routes require auth

---

## FEATURE 4: Self-Healing Mode — routes_healer.py

Proactive health monitoring and auto-recovery.

- `POST /healer/configure`
  Body: {auto_restart: true, max_errors_before_restart: 5, check_interval_seconds: 30, memory_limit_mb: 500}
  Returns: {status: "configured", ...}

- `GET /healer/config` — Returns current healer configuration
- `GET /healer/status` — Returns health status of all monitored components:
  ```json
  {
    "server": {"uptime": 3600, "status": "healthy"},
    "memory": {"rss_mb": 120, "limit_mb": 500, "status": "healthy"},
    "routes": {"total": 37, "healthy": 37, "failing": []},
    "errors_last_hour": 3,
    "restarts_today": 0,
    "last_check": "..."
  }
  ```
- `GET /healer/log` — Returns healer action log (restarts, warnings, recoveries)
- `POST /healer/check` — Force a health check immediately
- `POST /healer/restart` — Restart the CoAgent server process

How it works:
- Background thread runs every `check_interval_seconds`
- Checks:
  1. **Memory**: Query process memory via psutil (optional) or os.popen('tasklist'). If > limit, log warning. If exceeds 2x limit, auto-restart.
  2. **Route health**: Hit /ping, /version, /metrics — if any fail, mark as degraded
  3. **Error rate**: Count 5xx responses from routes_metrics counters. If > max_errors in a window, restart.
  4. **Response time**: If /ping takes > 5s, mark as degraded
- Writes actions to _healer_log list (max 100 entries, with lock)
- Configuration stored in COAGENT_DIR / "healer_config.json"
- Import psutil optionally (try/except)

Healing actions:
- Warning level: log to healer log, continue
- Degraded level: log + clear some caches (_sse_clients maybe)
- Critical level: log + restart the whole server via subprocess

For restart: use the same pattern as routes_updates.py (spawn python.exe hermes_coagent.py --secure after 1s delay, then sys.exit(0))

Write to: routes_healer.py
Blueprint: "healer"
Auth: all routes require auth

---

## FEATURE 5: Playwright Browser Automation — routes_browser_final.py

Finish the existing routes_browser.py stubs into a full browser automation module.

- `POST /browser/open` — Opens a browser window
  Body: {url: "https://google.com", headless: false, width: 1280, height: 720}
  Returns: {browser_id, status: "opened", url}

- `POST /browser/navigate/{browser_id}` — Navigate to a URL
  Body: {url: "https://..."}
  Returns: {status: "navigated", title: "Google"}

- `GET /browser/screenshot/{browser_id}` — Returns PNG screenshot of browser page

- `POST /browser/click/{browser_id}` — Click an element
  Body: {selector: "#search", or text: "Search"}
  Returns: {status: "clicked", selector: "#search"}

- `POST /browser/type/{browser_id}` — Type into an element
  Body: {selector: "#search", text: "hello world", enter: true}
  Returns: {status: "typed"}

- `POST /browser/extract/{browser_id}` — Extract text from page
  Body: {selector: "body"} (omit for full page text)
  Returns: {text: "...", title: "..."}

- `POST /browser/evaluate/{browser_id}` — Run JavaScript
  Body: {script: "document.title"}
  Returns: {result: "..."}

- `POST /browser/close/{browser_id}` — Close browser
- `GET /browser/list` — List all open browsers

How it works:
- Uses Playwright (from routes_browser.py, it's already imported as optional dep)
- Each browser instance runs in its own thread with sync_playwright()
- Store instances in _BROWSERS dict: {browser_id: {page, context, thread, created_at}}
- playwright.sync_api is already available from the existing routes_browser.py imports
- If playwright not installed, return 501 with "Playwright not installed"

Write to: routes_browser_final.py
Blueprint: "browser_v2"
Auth: all routes require auth

---

## FEATURE 6: Mobile Remote Control — routes_mobile.py + mobile.html

A lightweight mobile webapp for viewing and controlling the desktop from a phone.

### Backend: routes_mobile.py
- `GET /mobile` — Returns the mobile.html page
- `POST /mobile/tap` — Translates phone touch coordinates to desktop coordinates
  Body: {x: 100, y: 200} (phone coordinates, 0-100 percentage-based)
  Converts percentage to absolute desktop coords using screen resolution from /screen/jpeg metadata or shared constant (2560x1440 default)
  Then calls /mouse/click internally
  Returns: {status: "clicked", desktop_x: 960, desktop_y: 720}

- `POST /mobile/swipe` — Translates phone swipe to desktop drag
  Body: {x1: 10, y1: 50, x2: 90, y2: 50} (percentage-based)
  Converts to absolute, calls /mouse/drag
  Returns: {status: "swiped"}

- `POST /mobile/type` — Sends text to desktop keyboard
  Body: {text: "hello"}
  Returns: {status: "typed"}

- `POST /mobile/key` — Send special key
  Body: {key: "enter"}  (or "tab", "escape", "ctrl+v", etc.)
  Returns: {status: "pressed"}

- `GET /mobile/view` — Returns the current desktop view as JPEG (same as /screen/jpeg but with mobile-optimized scaling info)

### Frontend: Create mobile.html (served by routes_mobile.py)
- Full-screen desktop view that fills the phone screen
- Touch to tap (sends percentage-based coords)
- Pinch to zoom
- Keyboard bar at the bottom for text input + special keys
- Auto-refresh screen every 500ms using /mobile/view
- Status indicator showing connection
- Dark theme, touch-optimized (big targets, no tiny buttons)
- All API calls use Bearer token

The mobile page should be served inline as a string in routes_mobile.py (not a separate file for simplicity).

Write to: routes_mobile.py (contains both backend routes and the HTML as a string)
Blueprint: "mobile"
Auth: Only /mobile/view and /mobile (the page itself) should work without auth for easy loading — auth is done via the token stored in the page (passed as query param like ?token=xxx)

---

## INTEGRATION: Update hermes_coagent.py

After ALL 6 files exist, add imports (around line 600) and registrations (around line 660).

Use the same try/except pattern as existing modules:
```python
try:
    from routes_copilot_enhanced import register_routes as reg_copilot_enhanced
    COPILOT_ENHANCED_AVAILABLE = True
except ImportError:
    COPILOT_ENHANCED_AVAILABLE = False
```

Add features to the features dict:
```python
if COPILOT_ENHANCED_AVAILABLE:
    reg_copilot_enhanced(app, state, require_auth)
    features["copilot_enhanced"] = True
# ... same for all 6
```

## FINAL VERIFICATION
1. `python -m compileall -q .` — MUST pass
2. Read back dashboard.html and make sure it's valid HTML (not truncated)
3. All 6 features show up in /version features list when CoAgent starts
