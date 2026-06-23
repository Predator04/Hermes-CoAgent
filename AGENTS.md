# Hermes CoAgent - AGENTS.md (AI Onboarding Guide)

## Project Overview

Hermes CoAgent is a Flask-based Windows desktop automation server. Provides REST endpoints for desktop control: mouse, keyboard, OCR, UIA, screenshots, file ops, window management, notifications, browser automation, Google Workspace, agent gateway, and more. Runs on port 9123 behind Bearer token auth.

## Quick Start for AI Agents

```
1. Clone the repo
2. pip install -r requirements.txt (or pip install flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss)
3. cd CoAgent && python hermes_coagent.py --secure
4. POST /setup {"password":"yourpassword"} → get Bearer token
5. Send token as: Authorization: Bearer YOUR_TOKEN
```

**All endpoints require Bearer auth** (exceptions: /, /health, /ping, /version, /favicon.ico, /setup, /setup-status).

## Architecture

- **`hermes_coagent.py`** — Main server: auth, CORS, rate limiting, watchdog, endpoint health, route registration
- **Route modules** in same directory, registered via `register_routes(app, state, require_auth)`:

### Core Desktop Control
| Module | File | Endpoints |
|--------|------|-----------|
| 🖱️ Mouse/Keyboard | `routes_mouse.py` | click, move, scroll, drag, type, key combo, chain, emergency stop, smart click |
| 📸 OCR/Screenshots | `routes_ocr.py` | capture, screenshot, crop, OCR, describe, find text, FallbackChain (5 methods) |
| 🏗️ UIA | `routes_uia.py` | UIA tree, SOM overlays, element find by name/ID/type, window management |
| 🎬 Media/Windows | `routes_media.py` | wallpaper, window list/activate/move/resize, clipboard, macros, scheduler, tunneling, voice |
| ⚙️ Process | `routes_process.py` | list, start, kill, CPU/memory stats |
| 📁 File Ops | `routes_file.py` | read, write, delete (requires `confirm: true`), app launch, power management |
| 🔌 Cua Driver | `routes_cua.py` | 37 Cua Driver tools: accessibility tree, click, type, scroll, drag |
| 🎥 Stream | `routes_stream.py` | SSE screen streaming |
| 📦 v6.3 Features | `routes_v63.py` | cursor overlay, element-indexed UIA, desktop stabilization, session recording |

### AI & Automation
| Module | File | Endpoints |
|--------|------|-----------|
| 🤖 AI Co-Pilot | `routes_copilot.py` | observe (screenshot+OCR), suggest actions, automate UI flows |
| 🎙️ Voice | `routes_voice.py` | voice command recognition, speech-to-text |
| 🧑‍🤝‍🧑 Ember Buddy | `routes_buddy.py` | Ember desktop companion |
| 🔓 Bypass Toolkit | `routes_bypass.py` | 9 endpoints: leetspeak, homoglyph, zero-width, parseltongue, prefill templates, adversarial variants, trigger-word scan, auto-clean, one-shot all |
| **🆕 Agent Gateway** | `routes_agent.py` | See Agent Gateway section below |

### Health & Self-Healing
| Feature | Location | Behavior |
|---------|----------|----------|
| 🩺 Endpoint Health Tracker | `hermes_coagent.py` | Tracks ok/fail per endpoint, rolling 5-min windows |
| 🔄 Auto-Restart | background thread | >50% fail on 3+ endpoints → restarts |
| 💾 Config Backups | `routes_config.py` | Auto-backup config.json/.env before writes, keeps 20 versions |
| 🔁 Screenshot Fallback | `routes_ocr.py` | DXCam → MSS → PIL → Win32 → PowerShell |
| 📈 Memory Leak Detect | Watchdog thread | Warns >100MB/5min, restarts >150MB |
| 📦 Auto-Deps | `routes_deps.py` | Detect missing packages from logs, auto-install |

## Agent Gateway (v7.9.1)

Allows calling installed AI agent CLIs (Codex, Claude Code, Gemini CLI, OpenCode) as HTTP endpoints. Detects available agents automatically at startup.

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
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
  "model": "string (optional, e.g. gpt-5.5, claude-sonnet-4)",
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

### POST /agent/audit
```json
{
  "paths": ["."],
  "focus": "security|quality|all",
  "agent": "codex"
}
```

### POST /agent/plan
```json
{
  "task": "add bluetooth device discovery",
  "context": "Flask backend, pywin32, port 9123"
}
```

### POST /agent/implement
Same as plan but applies changes and reports modified files.

### POST /agent/plan vs /agent/implement
- `/agent/plan` — read-only, returns plan text without modifying files
- `/agent/implement` — applies changes, returns list of modified files

### Agent Auto-Detection
At startup, CoAgent scans PATH and known install locations for:
- **Codex** (`codex`, installed via npm: `npm install -g @openai/codex`)
- **Claude Code** (`claude`, installed via npm or pip)
- **Gemini CLI** (`gemini`, installed via npm)
- **OpenCode** (`opencode`, installed via npm)

Only detected agents appear as available. If none found, the gateway returns a clear error.

## API Quick Reference

### Bootstrapping
```
GET  /            — Dashboard HTML
GET  /ping        — {"status":"pong","agent":"...","uptime":N}
GET  /version     — agent name, version, feature list, module list
GET  /health      — {"status":"ok","agent":"...","version":"..."}
GET  /setup-status — {"configured":bool,"auth":bool,"setup_required":bool}
POST /setup       — {"password":"..."} → {"token":"...","status":"configured"}
```

### Desktop Control Examples
```bash
# Move mouse
curl -X POST http://127.0.0.1:9123/mouse/move \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Click
curl -X POST http://127.0.0.1:9123/mouse/click \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Type text
curl -X POST http://127.0.0.1:9123/key/type \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello world"}'

# Take screenshot (returns base64 JPEG)
curl -s http://127.0.0.1:9123/screen/base64 \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get UIA accessibility tree
curl -s http://127.0.0.1:9123/uia/tree \
  -H "Authorization: Bearer YOUR_TOKEN"

# Activate a window
curl -X POST http://127.0.0.1:9123/windows/activate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Notepad"}'

# List files
curl -X POST http://127.0.0.1:9123/file/list \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path":"C:\\Users\\Public"}'
```

## Security Notes

- Auth is enabled with `--secure`, `--token=KEY`, or `HERMES_COAGENT_TOKEN` env var
- First-time: `POST /setup {"password":"..."}` returns the Bearer token once
- Token stored in `.token` (gitignored). Use `.token` file or env var for scripts
- **Port 9123 controls the desktop — never expose to the internet**
- `--allow-external` binds `0.0.0.0` for LAN access; requires auth
- Dashboard stores token in `sessionStorage` (cleared on tab close)
- `/file/delete` requires `confirm: true` for directory deletion
- Plugin system blocks endpoints missing `require_auth` decorator
- CORS restricted to localhost origins
- Rate limit: 60 req/s per IP
- Security headers: X-Content-Type-Options, X-Frame-Options, Cache-Control

## Dependencies

Core: `flask`, `waitress`, `pillow`, `pyautogui`, `pywinauto`, `pytesseract`, `pygetwindow`, `pyperclip`, `pystray`, `mss`, `psutil`
Optional: `dxcam` (GPU screenshots), `playwright` (browser control), `google-api-python-client` + `google-auth-oauthlib` (Google Workspace), `win11toast` (notifications), `cryptography` (encrypted token storage)

## Coding Standards

- `register_routes(app, state, require_auth)` pattern for all route modules
- Auth: global `before_request` gate + per-route `@require_auth`
- Route helpers: `_json_payload()`, `_get_text()`, `_clamp_float()`, `_clamp_int()`
- Tests in `tests/` using Flask test client
- All responses are JSON (except dashboard HTML)
