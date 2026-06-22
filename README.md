# Hermes CoAgent v7.6

**Ultimate Desktop Co-Pilot for Windows** — gives AI agents (Hermes, Claude, Codex, Gemini, etc.) full native Windows desktop control. Screenshots, mouse/keyboard, UIA accessibility trees, OCR, voice, file ops, browser automation, notifications, Google Workspace, prompt bypass toolkit, and self-healing infrastructure. All local, zero API costs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🚀 Quick Start

```bash
# Install deps (Windows Python)
pip install flask pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray waitress mss dxcam playwright google-api-python-client google-auth-oauthlib win11toast

# Start CoAgent (secure mode)
cd C:\Users\Admin\Desktop\Hermes CoAgent
python hermes_coagent.py --secure --allow-external
# → Running on http://0.0.0.0:9123/
```

### From WSL / another machine
```bash
# Ping it
curl -s http://172.21.192.1:9123/ping
# → {"agent":"Hermes CoAgent v7.6","status":"pong"}

# See what's on screen
curl -s http://172.21.192.1:9123/describe

# Click something
curl -s -X POST http://172.21.192.1:9123/mouse/click \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Take screenshot
curl -s http://172.21.192.1:9123/screen/base64

# Get UIA tree (all windows + buttons)
curl -s http://172.21.192.1:9123/uia/tree
```

---

## 📦 What's in v7.6

### Self-Healing Infrastructure
| Feature | What it does |
|---------|-------------|
| 🩺 **Endpoint Health Tracker** | Tracks ok/fail per endpoint with rolling 5-min windows. Reports % success rate |
| 🔄 **Auto-Restart** | If >50% fail rate on 3+ endpoints → auto restarts CoAgent |
| 📸 **Screenshot Fallback Chain** | DXCam (GPU, 240fps) → MSS → PIL → Win32 API → PowerShell relay — 5 methods deep |
| 💾 **Config Backups** | Auto-backup config.json/.env before writes, keeps 20 versions, rollback endpoint |
| 📈 **Memory Leak Detection** | Watchdog tracks RSS growth — warns if >100MB/5min, auto-restarts if >150MB |
| 📦 **Auto-Deps Installer** | Scans error logs for ImportError, detects missing packages, installs automatically |
| 🔗 **FallbackChain Pattern** | Generic `FallbackChain` class — try N methods in order, report which succeeded |

### New Modules (v7.6)
| Module | Endpoints | What it does |
|--------|-----------|-------------|
| 🍞 **Toast Notifications** | `POST /toast/show`, `POST /toast/input` | Native Windows toast via win11toast |
| 🌐 **Browser Control** | `POST /browser/navigate`, `/click`, `/fill`, `/extract`, `/screenshot`, `/evaluate` | Full Playwright browser automation |
| 📧 **Google Workspace** | `POST /google/gmail/list`, `/gmail/send`, `/calendar/events`, `/calendar/create` | Gmail + Calendar API |
| 📝 **Log Analyzer** | `POST /logs/analyze` | Scan error logs, frequency stats, smart suggestions |
| 💾 **Config Manager** | `GET /config/backups`, `POST /config/rollback` | Config backup/rollback system |
| 📦 **Deps Manager** | `GET /deps`, `POST /deps/install`, `POST /deps/auto` | Check/install packages, auto-detect from logs |

### 🖥️ Full REST API

**Core**
`GET /` — dashboard · `GET /ping` — health · `GET /version` — version + features · `GET /health/endpoints` — per-endpoint health stats · `GET /stats` — server stats · `GET /logs` — server logs · `GET /events` — SSE stream · `GET /deps` — installed deps

**Mouse & Keyboard**
`POST /mouse/move` · `POST /mouse/click` · `POST /mouse/click/smart` (retry on unchanged screen) · `POST /mouse/dblclick` · `POST /mouse/rclick` · `POST /mouse/drag` · `POST /mouse/scroll` · `POST /key/type` · `POST /key/press` · `POST /chain` · `POST /act` · `POST /input/send` · `GET /cursor/pos` · `GET /copilot/mode`

**Screenshots & OCR** (with 5-deep fallback chain)
`GET /screen` · `GET /screen/jpeg` · `GET /screen/base64` · `GET /screen/fresh` · `GET /screen/diag` · `POST /ocr/find` · `POST /visual/find` · `POST /crop` · `GET /describe`

**UIA & SOM**
`GET /uia/tree` · `GET /uia/find/<name>` · `POST /uia/click` · `POST /uia/find-cmb` · `GET /uia/diag` · `GET /uia/window-tree` · `POST /uia/element/find` · `POST /uia/element/click-by-name` · `POST /uia/element/click-by-index` · `GET /som/screenshot` · `GET /som/cache/clear` · `GET /som/bridge` · `POST /som/point` · `GET /uia/accel-reg`

**Files & Power**
`POST /file/list` · `POST /file/read` · `POST /file/write` · `POST /file/delete` · `POST /app/open` · `POST /app/run` · `POST /power/sleep` · `POST /power/shutdown` · `POST /power/restart` · `POST /power/lock` · `POST /power/cancel`

**Windows & Wallpaper**
`GET /windows` · `POST /windows/activate` · `POST /wallpaper/set` · `POST /wallpaper/cycle` · `POST /wallpaper/random` · `GET /monitors` · `POST /monitors/layout`

**Clipboard & TTS**
`GET /clipboard/get` · `POST /clipboard/set` · `POST /tts/speak`

**Macros & Scheduler**
`POST /macro/list` · `POST /macro/save` · `POST /macro/run` · `POST /macro/record` · `POST /macro/delete` · `POST /replay` · `GET /scheduler/list` · `POST /scheduler/add` · `POST /scheduler/remove` · `POST /scheduler/run`

**Notifications & Browser**
`POST /toast/show` · `POST /toast/input` · `POST /browser/navigate` · `POST /browser/click` · `POST /browser/fill` · `POST /browser/extract` · `POST /browser/screenshot` · `POST /browser/evaluate`

**Google Workspace**
`POST /google/gmail/list` · `POST /google/gmail/send` · `POST /google/calendar/events` · `POST /google/calendar/create`

**Other**
`POST /voice/toggle` · `POST /tunnel/start` · `POST /tunnel/stop` · `GET /tunnel/status` · `POST /search/files` · `POST /launch/ai` · `POST /emergency/stop` · `POST /emergency/resume` · `GET /emergency/status` · `POST /logs/analyze` · `GET /config/backups` · `POST /config/rollback`

---

## 🔓 Bypass Toolkit (v7.5+)

All `/bypass/*` endpoints require Bearer auth. Prompt encoding, obfuscation, scanning, and prefill tools for working with AI content filters.

| Endpoint | Method | Description | Key Parameters |
|----------|--------|-------------|----------------|
| `/bypass` | GET | List all tools | — |
| `/bypass/leetspeak` | POST | Encode with leetspeak + Cyrillic homoglyphs | `intensity`, `use_cyrillic` |
| `/bypass/homoglyph` | POST | Encode with Unicode block | `block` (fullwidth/math_bold/math_mono/math_sans/fraktur/double_struck) |
| `/bypass/zero-width` | POST | Inject invisible zero-width chars | `frequency` |
| `/bypass/parseltongue` | POST | Multi-pass obfuscation | `passes` (1-5) |
| `/bypass/prefill` | GET/POST | List 5 templates or build prefill wrappers | `template` |
| `/bypass/adversarial` | POST | Generate 5+ adversarial input variants | — |
| `/bypass/scan` | POST | Scan for 77+ filter trigger words | — |
| `/bypass/clean` | POST | Auto-obfuscate only trigger words | — |
| `/bypass/all` | POST | One-shot scan + clean + prefill + encode | `template` |

**Prefill Templates:** `boundary_inversion`, `godmode_l33t`, `story_framing`, `educational_compatibility`, `prefill_assistant`

Trigger words: 77 words in `data/trigger_words.txt`. Max text: 100 KiB.

```bash
# Examples
TOKEN=<YOUR_TOKEN_HERE>
BASE=http://127.0.0.1:9123

# Scan for trigger words
curl -s -X POST "$BASE/bypass/scan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"I want to hack a computer"}'

# One-shot everything
curl -s -X POST "$BASE/bypass/all" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"exploit a vulnerability","template":"educational_compatibility"}'
```

---

## 🏗 Architecture (v7.6)

```
hermes_coagent.py          — Main server (268 lines coordinator)
├── shared_fallbacks.py    — FallbackChain: try N methods in order
├── routes_mouse.py        — Mouse/keyboard/chain/smart click (16 routes)
├── routes_ocr.py          — Screenshots/OCR/dxcam/fallback chain (11 routes)
├── routes_uia.py          — UIA tree/SOM overlays/element find (16 routes)
├── routes_file.py         — File ops/app launch/power (10 routes)
├── routes_media.py        — Wallpaper/clipboard/macros/scheduler (30+ routes)
├── routes_v63.py          — v6.3 features: cursor, recording, stabilization
├── routes_stream.py       — SSE screen streaming
├── routes_process.py      — Process management (psutil)
├── routes_voice.py        — Voice commands
├── routes_cua.py          — Cua Driver integration (37 tools)
├── routes_copilot.py      — AI Co-Pilot (observe/suggest/automate)
├── routes_buddy.py        — Ember desktop buddy
├── routes_bypass.py       — Prompt bypass toolkit (9 endpoints)
├── routes_toast.py        — 🆕 Windows toast notifications
├── routes_browser.py      — 🆕 Playwright browser automation
├── routes_google.py       — 🆕 Google Workspace (Gmail + Calendar)
├── routes_logs.py         — 🆕 Log analyzer
├── routes_config.py       — 🆕 Config manager + backups
├── routes_deps.py         — 🆕 Deps manager + auto-install
├── data/trigger_words.txt  — Filter trigger word list
├── tests/test_bypass.py    — Bypass toolkit unit tests
├── AGENTS.md               — AI onboarding guide
├── uia_engine.py           — UIA accessibility tree + SOM engine
├── computer_use_mcp.py     — FastMCP server (proxy to HTTP API)
├── coagent_client.py       — Python client library
└── tray_icon.py            — System tray + screenshot relay
```

**Data flow:** AI Agent → HTTP API → CoAgent → Windows APIs → Desktop

---

## 🔐 Security

| Flag | Effect |
|------|--------|
| `--secure` | Enable Bearer auth using the saved `.token` file or first-time setup |
| `--token=KEY` | Enable Bearer auth with a provided token and save it to `.token` |
| `HERMES_COAGENT_TOKEN` | Enable Bearer auth from an environment variable |
| `--allow-external` | Bind `0.0.0.0` for LAN access; requires auth |

First-time setup:

```bash
python hermes_coagent.py --secure
curl -s -X POST http://127.0.0.1:9123/setup \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"yourpassword\"}"
```

The setup response returns the Bearer token once. Save it and send it on control/data requests:

```bash
curl -s http://127.0.0.1:9123/uia/tree \
  -H "Authorization: Bearer <token>"
```

All control and data endpoints require `Authorization: Bearer <token>`. Bootstrap/status endpoints are limited to `/`, `/health`, `/ping`, `/version`, `/favicon.ico`, `/setup`, and `/setup-status`.

The token file is `.token`; `.token` and `.token_*` are gitignored, and the git commit route enforces that before staging. Port 9123 controls the desktop and should never be exposed to the internet. Use `--allow-external` only on trusted local networks with auth enabled.

---

## 🔧 Requirements

- **Windows 10/11**
- **Python 3.8+**
- **Core deps:** `flask pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray waitress mss`
- **v7.6 deps:** `dxcam playwright google-api-python-client google-auth-oauthlib win11toast`

---

## 📄 License

MIT — see [LICENSE](LICENSE)
