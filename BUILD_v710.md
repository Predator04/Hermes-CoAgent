# CoAgent v7.10 — Build these 4 modules

Build ALL 4 modules described below. Each gets its own file in C:\Users\Admin\Desktop\Hermes CoAgent\. Files go next to routes_agent.py etc. Register each in hermes_coagent.py.

## MODULE 1: metrics.py — Prometheus-style metrics endpoint

Create `/routes_metrics.py` with:
- Module-level counters: `REQUESTS = Counter()`, `ERRORS = Counter()`, `LATENCY_HISTOGRAM = [...]`
- `@app.before_request` hook that tracks start time per request
- `@app.after_request` hook that increments counters, records latency
- `GET /metrics` returns Prometheus-text-format output:
  ```
  # HELP coagent_requests_total Total HTTP requests
  # TYPE coagent_requests_total counter
  coagent_requests_total{method="GET",path="/ping",status="200"} 42
  # HELP coagent_request_duration_seconds Request duration
  # TYPE coagent_request_duration_seconds histogram
  coagent_request_duration_seconds{method="GET",path="/ping",le="0.01"} 30
  ...
  # HELP coagent_active_connections Current SSE/stream connections
  # TYPE coagent_active_connections gauge
  coagent_active_connections 3
  # HELP coagent_memory_rss_bytes Process memory in bytes
  # TYPE coagent_memory_rss_bytes gauge
  coagent_memory_rss_bytes 98765432
  ```
- Memory tracking: import psutil (make it optional — graceful fallback if not installed). Try to use `os` and `/proc/self/status` approach for Windows too.
- Track: endpoint, method, status code, duration buckets (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, +Inf)
- The /metrics endpoint itself should NOT be counted in metrics (to avoid infinite loop)
- Include SSE connection count by checking shared._sse_clients and routes_agent.ACTIVE_STREAMS

Write to: routes_metrics.py

Registration function: `def register_routes(app, state, require_auth):` (standard pattern)
Route: GET /metrics (auth-exempt since it's monitoring)
Blueprint name: "metrics"

The `require_auth` param is a decorator function — just wrap the route with it.

## MODULE 2: docs.py — OpenAPI/Swagger docs

Create `/routes_docs.py` with:
- Hardcoded OpenAPI 3.0 spec as a dict describing every route in the codebase
- GET /docs.json returns the JSON spec
- GET /docs returns an HTML page that renders the spec using Swagger UI (inline CDN link to unpkg.com/swagger-ui-dist)
- Include ALL these routes grouped by tag:
  - **Core**: GET /ping, GET /version, GET /health
  - **Mouse**: POST /mouse/move, /mouse/click, /mouse/dblclick, /mouse/rclick, /mouse/drag, /mouse/scroll, GET /cursor/pos  
  - **Keyboard**: POST /key/type, /key/press
  - **Screen**: GET /screen/jpeg, GET /screen/base64, GET /screen/describe, GET /som/screenshot
  - **UIA**: GET /uia/tree, GET /uia/find/{name}, POST /uia/click/{name}
  - **Windows**: GET /windows, POST /windows/activate, POST /windows/close, GET /windows/{pid}
  - **Files**: POST /file/list, POST /file/read, POST /file/write, POST /file/delete, POST /file/upload
  - **Agent Gateway**: POST /agent/exec, POST /agent/audit, POST /agent/plan, POST /agent/status, GET /agent/exec/stream/{log_id}
  - **Telegram**: POST /telegram/configure, POST /telegram/send, GET /telegram/config
  - **Config**: GET /config, POST /config/update
  - **Metrics**: GET /metrics
  - **System**: POST /process/start, GET /process/list, POST /power/shutdown, POST /power/restart
  - **Clipboard**: POST /clipboard/get, POST /clipboard/set
  - **Macro**: POST /macro/list, POST /macro/save, POST /macro/run
  - **Webhooks**: POST /webhooks/register, GET /webhooks/list, DELETE /webhooks/{id}
  - **Updates**: GET /update/check, POST /update/apply
  - **Plugins**: GET /plugins/list, POST /plugins/install, POST /plugins/uninstall
- For each route include: summary, description, parameters (query/body), response schemas
- Keep the OpenAPI spec as a compact but complete dict — the file should be well-organized
- Use `COAGENT_DIR`, `VERSION`, `AGENT_NAME` from shared for version/description fields

Write to: routes_docs.py

Registration function: `def register_routes(app, state, require_auth):`
Routes: GET /docs (auth-exempt, returns HTML), GET /docs.json (auth-exempt, returns JSON)

## MODULE 3: updates.py — Auto-updater

Create `/routes_updates.py` with:
- GET /update/check — queries GitHub API (api.github.com/repos/Predator04/Hermes-CoAgent/releases/latest) and returns:
  ```json
  {"current": "7.9.1", "latest": "7.9.2", "update_available": true, "release_url": "...", "published_at": "..."}
  ```
- POST /update/apply — downloads the latest release zip from GitHub, extracts over current directory, restarts the server:
  1. Check current version vs latest
  2. If same, return 304
  3. Download zip from GitHub releases (tarball URL: https://api.github.com/repos/Predator04/Hermes-CoAgent/tarball/main)
  4. Extract to a temp directory
  5. Copy files over current COAGENT_DIR (preserving .token, telegram_config.json, config.json)
  6. Touch a restart flag file
  7. Return 200 with {status: "ok", version: "x.y.z", restarting: true}
  8. The server should restart via a subprocess launch of itself (pythonw.exe hermes_coagent.py --secure) after a 1s delay
- Use shared.COAGENT_DIR for paths
- POST /update/restart — simply restarts the CoAgent process (useful after manual updates)
- Use `import urllib.request` for HTTP, `import zipfile` or `import tarfile` for extraction
- Token/credential files to preserve during update: .token, telegram_config.json, config.json
- Reference shared.VERSION for current version

Write to: routes_updates.py

Registration function: `def register_routes(app, state, require_auth):`

## MODULE 4: webhooks.py — Webhook system

Create `/routes_webhooks.py` with:
- In-memory store: `_WEBHOOKS = {}` (dict of id -> {url, events: list, secret: str, created_at, last_triggered, last_response})
- Threading lock for safety
- GET /webhooks/list — returns all registered webhooks (without secrets)
- POST /webhooks/register — body: {url, events: ["screenshot_taken", "error", "agent_completed", "user_login"]}  
  Returns: {id, url, events, created_at}
- DELETE /webhooks/{id} — removes a webhook
- POST /webhooks/test/{id} — fires a test event to the webhook URL
- Function `fire_webhook(event_type, data)` that:
  1. Checks _WEBHOOKS for any matching event_type
  2. Sends HTTP POST with JSON body: {event, data, timestamp, webhook_id}
  3. Includes HMAC-SHA256 signature in X-Webhook-Signature header using the webhook's secret
  4. Runs in a background thread (don't block the caller)
  5. Updates last_triggered and last_response on the webhook record
- Use `threading.Thread` for async dispatch, `urllib.request` for HTTP POSTs
- hmac for signature: `hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()`
- Fire a webhook for these events by default (called from routes_* modules):
  - route can call `fire_webhook("screenshot_saved", {"path": path})` etc.

Write to: routes_webhooks.py

Registration function: `def register_routes(app, state, require_auth):`

## INTEGRATION: Update hermes_coagent.py

Add these imports after the existing module imports around line 575:
```python
try:
    from routes_metrics import register_routes as reg_metrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    _console("[WARN] routes_metrics.py not found")

try:
    from routes_docs import register_routes as reg_docs
    DOCS_AVAILABLE = True
except ImportError:
    DOCS_AVAILABLE = False
    _console("[WARN] routes_docs.py not found")

try:
    from routes_updates import register_routes as reg_updates
    UPDATES_AVAILABLE = True
except ImportError:
    UPDATES_AVAILABLE = False
    _console("[WARN] routes_updates.py not found")

try:
    from routes_webhooks import register_routes as reg_webhooks
    WEBHOOKS_AVAILABLE = True
except ImportError:
    WEBHOOKS_AVAILABLE = False
    _console("[WARN] routes_webhooks.py not found")
```

Add these registration calls after the existing `reg_*()` calls (around line 620):
```python
    if METRICS_AVAILABLE:
        reg_metrics(app, state, require_auth)
        features["metrics"] = True
    if DOCS_AVAILABLE:
        reg_docs(app, state, require_auth)
        features["docs"] = True
    if UPDATES_AVAILABLE:
        reg_updates(app, state, require_auth)
        features["updates"] = True
    if WEBHOOKS_AVAILABLE:
        reg_webhooks(app, state, require_auth)
        features["webhooks"] = True
```

## Final verification
After all changes:
1. `python -m compileall -q .` — must pass
2. Start CoAgent and verify: GET /metrics, GET /docs, GET /docs.json, GET /update/check, GET /webhooks/list all return valid responses

## IMPORTANT NOTES:
- Each file is STANDALONE with its own imports
- Follow the existing pattern: Blueprint named after the module, register_routes(app, state, require_auth)
- `require_auth` is a decorator — wrap the route handler with `@require_auth`
- For auth-exempt routes (docs, metrics), DON'T use @require_auth — they're public
- Use `from shared import COAGENT_DIR, VERSION, AGENT_NAME, _console, _json_body, _sse_clients, get_host_ip, SERVER_PORT` as needed
- All responses should be jsonify() unless noted otherwise
- Keep routes_agent.ACTIVE_STREAMS reference optional (try/except ImportError)
