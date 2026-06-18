# Codex Review

Date: 2026-06-18

## Scope

- Ran `git diff HEAD~1 --stat`.
- Read changed Python files: `ROUTE_MAP.py`, `auth.py`, `computer_use_mcp.py`, `cua_mcp_bridge.py`, `hermes_coagent.py`, `uia_engine.py`.
- Read `dashboard.html`.
- Reviewed for bugs, security issues, XSS, races, dead code, auth issues, and route inconsistencies.

## Findings And Fixes

### Fixed: secure-mode auth bypass list was too broad

`hermes_coagent.py` had `AUTH_EXEMPT_PREFIXES` and `AUTH_EXEMPT_PATHS` entries for sensitive APIs including screenshots, UIA/SOM data, power controls, wallpaper, tunnel, macros, scheduler, clipboard, search, replay, voice, logs, history, stats, and window data. In `--secure` / token mode, those routes could bypass the global `before_request` Bearer-token gate.

Patch:

- Narrowed `AUTH_EXEMPT_PREFIXES` to `/static`.
- Narrowed `AUTH_EXEMPT_PATHS` to `/`, `/dashboard2`, `/health`, `/ping`, `/version`, and `/favicon.ico`.

### Fixed: route-map auth documentation was stale

`ROUTE_MAP.py` still described `--allow-external` as requiring only `--secure` and did not document env-token support or the secure-mode global auth contract.

Patch:

- Documented `--secure`, `--token`, and `HERMES_COAGENT_TOKEN`.
- Documented the exact secure-mode public route exceptions.

## Reviewed Existing Diff Content

The current changed files already include fixes for the other high-risk items checked in this pass:

- Dashboard XSS sinks use `textContent` / `replaceChildren` instead of rendering user-controlled data with `innerHTML`.
- Dashboard API calls and screenshot/history fetches can send Bearer auth from stored/query token state.
- MCP proxy uses canonical CoAgent routes and supports `COAGENT_TOKEN` / `HERMES_COAGENT_TOKEN`.
- UIA stable-ID and accelerated-region shared maps are lock-protected.
- SendInput hotkey chords press keys down together, while text typing sends characters sequentially.
- File path sanitization uses resolved path boundaries instead of raw string prefix matching.
- Macro names are constrained to single safe filenames.

## Verification

- `python -m py_compile ROUTE_MAP.py auth.py computer_use_mcp.py cua_mcp_bridge.py hermes_coagent.py uia_engine.py` passed.
- `git diff --check` passed.
- Removed generated `cpython-312` `__pycache__` files after syntax verification.

## Remaining Notes

- Default localhost/no-auth mode remains intentionally available per project docs.
- In secure/token mode, the dashboard shell is public but API, screenshot, history, and control calls now require Bearer auth.
