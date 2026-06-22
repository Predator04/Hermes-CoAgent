Fix ALL bugs found in the latest Codex audit of Hermes CoAgent. Do NOT stop until every fix is applied and compiles.

## Bugs to Fix

### 1. 🔴 /chain crash (routes_mouse.py:267-270)
The `/chain` endpoint crashes on successful actions. It does `result = r[0]` but Flask `Response` is not subscriptable.
Fix: Change the chain execution to check if the result is a tuple (Flask response, status_code) before subscripting.

### 2. 🔴 Module import kills CoAgent (hermes_coagent.py:310-319)
The singleton mutex at module level runs `taskkill` against pythonw.exe when imported. Move mutex creation into the `if __name__ == "__main__"` block or protect it with a flag.

### 3. 🟠 /mouse/move accidentally clicks (routes_mouse.py:115-129, 177-178)
`_background_sendinput()` emits mouse down/up events. For move actions, use `SetCursorPos` directly via ctypes instead.

### 4. 🟠 Tunnel starts before validation (routes_media.py:560-590)
If timeout is invalid, the endpoint returns 400 but the tunnel process is already running.
Fix: Validate ALL parameters BEFORE starting the tunnel process.

### 5. 🟠 Git/WOL/scheduler race conditions
Routes: routes_git.py:73-99, routes_wol.py:83-85, routes_wol.py:95-100, routes_media.py:392-410
Add `threading.Lock()` to protect file operations. Fail fast if lock is contended.

### 6. 🟠 Session recording broken (coagent_features.py:542-587, routes_v63.py:82-107)
`record_action()` is defined but never called from any action route.
Fix: In each core route (mouse click, key type, etc.), call `record_action(action_name, params, state)` after the action succeeds.

### 7. 🟡 Endpoint health monitor never starts (hermes_coagent.py:460-486, 884-889)
`_start_endpoint_health_monitor()` is defined but never called in `__main__`.
Fix: Add a call to it before `waitress.serve()`.

### 8. 🔵 Dead code sweep
Remove unused imports from: hermes_coagent.py (json, send_file, _json_body), shared.py (base64, functools, re, secrets, time, traceback, datetime, BytesIO), routes_deps.py (try_import), routes_mcp.py (_json_payload), routes_mouse.py (_limit_arg), uia_engine.py (_mark_region_changed, _mark_region_stable, _get_cold_regions).

## Verify Each Fix
After each fix, run `python -c "import py_compile; py_compile.compile('FILE.py', doraise=True)"` to ensure it compiles.

Then run `python -m compileall -q .` on the whole directory.

Do NOT stop until ALL fixes are applied and ALL files compile.
