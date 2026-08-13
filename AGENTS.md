# Hermes CoAgent — AI Agent Onboarding Guide

## Project Overview

Hermes CoAgent is a Flask-based Windows desktop automation server. Provides REST endpoints for desktop control: mouse, keyboard, OCR, UIA, screenshots, file ops, window management, notifications, browser automation, Google Workspace, agent gateway, and more. Runs on port 9123 behind Bearer token auth.

## Quick Start for AI Agents

```
1. Clone the repo
2. pip install -r requirements.txt
3. python hermes_coagent.py --secure --allow-external
4. Read token from ./.token (auto-generated on first run)
5. Send token as: Authorization: Bearer <token>
```

**Auth-exempt endpoints:** `/ping`, `/version`, `/health`, `/help`, `/setup`, `/setup-status`, `/dashboard`, `/favicon.ico`, `/static/*`.
All other endpoints require Bearer auth when `--secure` is active.

## Version

Version is stored in `VERSION` file (single source of truth). All Python modules read it at runtime.
- Check: `python scripts/bump_version.py`
- Bump: `python scripts/bump_version.py patch|minor|major`

## Architecture

- **`hermes_coagent.py`** — Main server: auth, CORS, rate limiting, watchdog, endpoint health, route registration
- **`shared.py`** — Shared utilities: VERSION loader, logging, JSON helpers, SSE, fallback chains
- Route modules registered via `register_routes(app, state, require_auth)`:

### Core Desktop Control

| Module | Endpoints |
|---|---|
| `routes_mouse.py` | click, move, scroll, drag, type, key combo, chain, emergency stop, smart click |
| `routes_ocr.py` | capture, screenshot, crop, OCR, describe, find text, FallbackChain (5 methods) |
| `routes_uia.py` | UIA tree, SOM overlays, element find by name/ID/type, window management |
| `routes_system.py` | System info, volume control, brightness, media keys, monitor control |
| `routes_media.py` | Wallpaper, window list/activate/move/resize, clipboard, macros, scheduler, tunneling, voice |
| `routes_process.py` | List, start, kill, CPU/memory stats |
| `routes_file.py` | Read, write, delete (requires `confirm: true`), app launch, power management |
| `routes_cua.py` | Cua Driver tools: accessibility tree, click, type, scroll, drag |
| `routes_stream.py` | SSE screen streaming |
| `routes_webcam.py` | Webcam capture |

### AI & Automation

| Module | Endpoints |
|---|---|
| `routes_agent.py` | Agent gateway — Codex, Claude, Gemini, OpenCode CLI execution |
| `routes_copilot.py` | Observe (screenshot+OCR), suggest actions, automate UI flows |
| `routes_copilot_enhanced.py` | Multi-step goal execution with SSE progress tracking |
| `routes_bypass.py` | AI bypass toolkit: leetspeak, homoglyph, zero-width, prefill templates |
| `routes_voice.py` | Voice command recognition, speech-to-text |
| `routes_mcp.py` | JSON-RPC MCP bridge — auto-discovers CoAgent endpoints as MCP tools |

### Browser Automation

| Module | Endpoints |
|---|---|
| `routes_browser.py` | Playwright browser control (single-session) |
| `routes_browser_final.py` | Thread-owned browser sessions (multi-browser) |
| `routes_stealth_browser.py` | Undetectable browser — 13 anti-detection patches, Cloudflare bypass |

### Health & Self-Healing

| Feature | Location | Behavior |
|---|---|---|
| Endpoint Health Tracker | `hermes_coagent.py` | Tracks ok/fail per endpoint, rolling 5-min windows |
| Auto-Restart | Background thread | >50% fail on 3+ endpoints → restarts |
| Config Backups | `routes_config.py` | Auto-backup before writes, keeps 20 versions |
| Screenshot Fallback | `routes_ocr.py` | DXCam → MSS → PIL → Win32 → PowerShell |
| Memory Leak Detect | Watchdog thread | Warns >100MB/5min, restarts >150MB |
| Auto-Deps | `routes_deps.py` | Detect missing packages from logs, auto-install |

## Agent Gateway

Allows calling installed AI agent CLIs (Codex, Claude Code, Gemini CLI, OpenCode) as HTTP endpoints.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/status` | List detected agents, versions, availability |
| `POST` | `/agent/exec` | Run any agent with a prompt |
| `POST` | `/agent/audit` | Security/quality audit of files |
| `POST` | `/agent/plan` | Generate implementation plan |
| `POST` | `/agent/implement` | Plan + auto-apply changes |
| `GET` | `/agent/logs` | View agent execution history |

### POST /agent/exec

```json
{
  "prompt": "string (required)",
  "agent": "codex|claude|gemini|opencode (optional, auto-detects first available)",
  "model": "string (optional)",
  "timeout": 300,
  "workdir": "string (optional, defaults to CoAgent dir)"
}
```

Response:
```json
{
  "success": true,
  "agent": "codex",
  "output": "...agent stdout/stderr...",
  "exit_code": 0,
  "duration_seconds": 45.2,
  "files_modified": ["file1.py", "file2.py"],
  "log_id": "20260622_094523"
}
```

## API Quick Reference

### Bootstrapping

```
GET  /ping         — {"status":"pong","agent":"Hermes CoAgent","uptime":N}
GET  /version      — Agent name, version, build, feature list
GET  /health       — {"status":"ok","agent":"...","version":"..."}
GET  /help         — Full API catalog (JSON or text)
GET  /dashboard    — Operator HTML dashboard
```

### Desktop Control Examples

```bash
# Move mouse
curl -X POST http://127.0.0.1:9123/mouse/move \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Click
curl -X POST http://127.0.0.1:9123/mouse/click \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Type text
curl -X POST http://127.0.0.1:9123/key/type \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello world"}'

# Screenshot (base64 JPEG)
curl -s http://127.0.0.1:9123/screen/base64 \
  -H "Authorization: Bearer <token>"

# UIA accessibility tree
curl -s http://127.0.0.1:9123/uia/tree \
  -H "Authorization: Bearer <token>"

# Activate a window
curl -X POST http://127.0.0.1:9123/windows/activate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Notepad"}'
```

## Security

- Auth enabled with `--secure`, `--token=KEY`, or `HERMES_COAGENT_TOKEN` env var
- Token stored in `.token` (gitignored)
- **Port 9123 controls the desktop — never expose to the internet without a reverse proxy**
- `--allow-external` binds `0.0.0.0` for LAN access; requires auth
- CORS restricted to localhost origins
- Rate limit: 60 req/s per IP
- Security headers: X-Content-Type-Options, X-Frame-Options, Cache-Control

## Dependencies

Core: `flask`, `waitress`, `pillow`, `pyautogui`, `pywinauto`, `pytesseract`, `pygetwindow`, `pyperclip`, `pystray`, `mss`, `psutil`

Optional: `dxcam` (GPU screenshots), `playwright`/`patchright` (browser control), `google-api-python-client` + `google-auth-oauthlib` (Google Workspace), `win11toast` (notifications), `cryptography`

## Coding Standards

- `register_routes(app, state, require_auth)` pattern for all route modules
- Auth: global `before_request` gate + per-route `@require_auth`
- Route helpers: `_json_payload()`, `_get_text()`, `_clamp_float()`, `_clamp_int()`
- Tests in `tests/` using Flask test client
- All responses are JSON (except dashboard HTML)
- Version: read from `VERSION` file — never hardcode version strings
