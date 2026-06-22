# Hermes CoAgent - AGENTS.md (AI Onboarding Guide)

## Project Overview

Hermes CoAgent is a Flask-based Windows desktop automation server. Provides REST endpoints for desktop control: mouse, keyboard, OCR, UIA, screenshots, file ops, window management, notifications, browser automation, Google Workspace, and more. Runs on port 9123 behind Bearer token auth.

## Getting Started

- Launch: `C:\Program Files\Python312\python.exe hermes_coagent.py --token=TOKEN --allow-external`
- Python: `C:\Program Files\Python312\python.exe`
- Working dir: `C:\Users\Admin\Desktop\Hermes CoAgent\`
- Token: `YOUR_TOKEN_HERE`
- Health: `GET /health`
- Version: `GET /version`
- Dashboard: `GET /`

## Architecture (v7.6)

- **`hermes_coagent.py`** — Main server: auth, CORS, rate limiting, watchdog, endpoint health tracker, route registration, module loading
- **Route modules** in same directory:

### Core Desktop Control
| Module | File | Endpoints |
|--------|------|-----------|
| 🖱️ Mouse/Keyboard | `routes_mouse.py` | click, move, scroll, drag, type, key combo, chain actions, emergency stop, smart click (with retry on unchanged screen) |
| 📸 OCR/Screenshots | `routes_ocr.py` | capture, screenshot, crop, OCR, describe, find text, FallbackChain (DXCam → MSS → PIL → Win32 → PowerShell relay) |
| 🏗️ UIA | `routes_uia.py` | UIA tree, SOM overlays, element find by name/ID/control type, accelerated regions, window management |
| 🎬 Media/Windows | `routes_media.py` | wallpaper, window list/activate/move/resize, clipboard, macros, scheduler, tunneling (cloudflare/ngrok), voice |
| ⚙️ Process | `routes_process.py` | list, start, kill, CPU/memory stats |
| 📁 File Ops | `routes_file.py` | read, write, delete, download, app launch, power management (shutdown/restart/lock/sleep) |
| 🔌 Cua Driver | `routes_cua.py` | 37 Cua Driver tools: accessibility tree, window state, click, type, scroll, drag, element index |
| 🎥 Stream | `routes_stream.py` | SSE screen streaming |
| 📦 v6.3 Features | `routes_v63.py` | cursor overlay, element-indexed UIA, desktop stabilization, session recording |

### AI & Automation
| Module | File | Endpoints |
|--------|------|-----------|
| 🤖 AI Co-Pilot | `routes_copilot.py` | observe (screenshot+OCR), suggest actions, automate UI flows |
| 🎙️ Voice | `routes_voice.py` | voice command recognition, speech-to-text |
| 🧑‍🤝‍🧑 Ember Buddy | `routes_buddy.py` | Ember desktop companion |
| 🔓 Bypass Toolkit | `routes_bypass.py` | 9 endpoints: leetspeak, homoglyph, zero-width, parseltongue, prefill templates, adversarial variants, trigger-word scan, auto-clean, one-shot all |

### New in v7.6
| Module | File | Endpoints |
|--------|------|-----------|
| 🍞 Toast Notifications | `routes_toast.py` | `POST /toast/show` — native Windows toast via win11toast. `POST /toast/input` — input-prompting toast |
| 🌐 Browser (Playwright) | `routes_browser.py` | `POST /browser/navigate`, `/click`, `/fill`, `/extract`, `/screenshot`, `/evaluate` — full Playwright browser automation |
| 📧 Google Workspace | `routes_google.py` | `POST /google/gmail/list`, `/gmail/send`, `/calendar/events`, `/calendar/create` — Gmail + Calendar |
| 📝 Log Analyzer | `routes_logs.py` | `POST /logs/analyze` — scan error logs, frequency stats, smart suggestions |
| 💾 Config Manager | `routes_config.py` | `GET /config/backups`, `POST /config/rollback` — auto-backup config files, rollback history |
| 📦 Deps Manager | `routes_deps.py` | `GET /deps` — check installed deps. `POST /deps/install` — install specific. `POST /deps/auto` — auto-detect missing from logs + install |
| 📷 DXCam Screenshot | (in `routes_ocr.py`) | GPU-accelerated 240fps capture via FallbackChain. Lazy init — won't crash from Session 0 |
| 🔗 Fallback Chains | `shared_fallbacks.py` | `FallbackChain` class — try N methods in order, report which succeeded |

### Health & Self-Healing
| Feature | Location | Behavior |
|---------|----------|----------|
| 🩺 Endpoint Health Tracker | `hermes_coagent.py` | Tracks ok/fail per endpoint, rolling 5-min windows, success rates |
| 🔄 Auto-Restart | background thread | If >50% fail rate on 3+ endpoints → restarts CoAgent |
| 💾 Config Backups | `routes_config.py` | Auto-backup `config.json` and `.env` before writes, keeps 20 versions |
| 🔁 Screenshot Fallback | `routes_ocr.py` | DXCam → MSS → PIL → Win32 API → PowerShell relay — 5 methods deep |
| 📈 Memory Leak Detect | Watchdog in `hermes_coagent.py` | Tracks RSS growth — warns if >100MB/5min, auto-restarts if >150MB |
| 📦 Auto-Deps | `routes_deps.py` | Scans error logs, detects missing packages, auto-installs |
| 🔗 Fallback Chains | `shared_fallbacks.py` | Generic pattern: try method A, if fails try B, etc. with timing |

## Coding Standards

- Flask Blueprints with `register_routes(app, state, require_auth)` pattern
- Auth: global `before_request` in `hermes_coagent.py`
- Route helpers: `_json_payload()`, `_get_text()`, `_clamp_float()`, `_clamp_int()`
- Max text: 100 KiB per request
- Tests: `tests/` using Flask test client
- Bypass trigger words: `data/trigger_words.txt`

## Deployment / Self-Healing

- **Watchdog** (`coagent_watchdog.ps1`): PowerShell script runs every 60s via scheduled task `HermesCoAgent-Watchdog`
  - Detects dead/unresponsive CoAgent (HTTP ping + process check)
  - Launches CoAgent on Session 1 interactive desktop via `schtasks /IT /RL HIGHEST`
  - Also monitors screenshot relay (port 9124), restarts if down
  - Logs to `C:\Windows\Temp\coagent_watchdog.log`
- **Install**: Run `install_watchdog.ps1` as Admin (copies script to `C:\Windows\Temp\` for reliable schtasks invocation)
- **Manual launch**: `C:\Program Files\Python312\python.exe hermes_coagent.py --token=TOKEN --allow-external`
- Python 3.12.9 at `C:\Program Files\Python312\python.exe`
- Working dir: `C:\Users\Admin\Desktop\Hermes CoAgent\`
- Token: `YOUR_TOKEN_HERE`

## Security

- Auth is enabled with `--secure`, `--token=TOKEN`, or the `HERMES_COAGENT_TOKEN` environment variable.
- First-time secure setup: launch with `--secure` on localhost, then `POST /setup` with `{"password":"yourpassword"}`. The response returns the Bearer token once.
- Send `Authorization: Bearer <token>` to all control and data endpoints. Bootstrap/status endpoints are limited to `/`, `/health`, `/ping`, `/version`, `/favicon.ico`, `/setup`, and `/setup-status`.
- The token is stored in `.token`; `.token` and `.token_*` are gitignored and the git commit route enforces that before staging.
- Port 9123 controls the desktop and must not be exposed to the internet. Use `--allow-external` only on trusted local networks with auth enabled.

## Requirements
- Core deps: `flask`, `waitress`, `mss`, `pywinauto`, `psutil`
- v7.6 deps: `dxcam`, `playwright`, `google-api-python-client`, `google-auth-oauthlib`, `win11toast`

## API Notes

- All endpoints behind `require_auth` unless in AUTH_EXEMPT_PATHS/AUTH_EXEMPT_PREFIXES
- `POST` endpoints generally expect `application/json`
- See `README.md` and route module docstrings for full endpoint details
- v7.5b → v7.6: Added 14 new endpoints across 6 new modules + health tracker + fallback chain
