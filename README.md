# Hermes CoAgent v7.8

**Ultimate Desktop Co-Pilot for Windows** — gives AI agents full native Windows desktop control via a REST API. Screenshots, mouse/keyboard, UIA accessibility trees, OCR, voice, file ops, browser automation, notifications, Google Workspace, prompt bypass toolkit, agent gateway, and self-healing infrastructure. All local, zero API costs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🚀 Quick Start

### Prerequisites
- Windows 10/11
- Python 3.8+ installed

### Install & Run
```bash
# 1. Clone
git clone https://github.com/Predator04/Hermes-CoAgent.git
cd Hermes-CoAgent

# 2. Install dependencies
pip install flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss psutil

# 3. Start with secure auth
python hermes_coagent.py --secure

# 4. First-time setup (one-time)
curl -s -X POST http://127.0.0.1:9123/setup \
  -H "Content-Type: application/json" \
  -d '{"password":"yourpassword"}'

# → Returns your Bearer token (save it!)
```

### Test It
```bash
# Set your token
TOKEN=***your-bearer-token-here***

# Health check
curl -s http://127.0.0.1:9123/ping

# See version + features
curl -s http://127.0.0.1:9123/version

# Check agent gateway status
curl -s http://127.0.0.1:9123/agent/status \
  -H "Authorization: Bearer $TOKEN"

# Take a screenshot
curl -s http://127.0.0.1:9123/screen/base64 \
  -H "Authorization: Bearer $TOKEN"

# Get UIA accessibility tree
curl -s http://127.0.0.1:9123/uia/tree \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📦 What's in v7.8

### 🆕 Agent Gateway (v7.8)
Call installed AI agents (Codex, Claude Code, Gemini CLI, OpenCode) as HTTP endpoints:

```bash
POST /agent/exec {"prompt":"audit the codebase", "agent":"codex"}
POST /agent/audit {"paths":["."], "focus":"security"}
POST /agent/implement {"task":"add bluetooth discovery"}
GET  /agent/status
GET  /agent/logs
```

Full docs in `AGENTS.md`.

### 🆕 Security Hardening (v7.8)
| Fix | What changed |
|-----|-------------|
| Token rotation | No hardcoded tokens in source |
| Plugin auth | Blocks plugins with unprotected endpoints |
| File delete guard | Requires `confirm: true`, protects user dirs |
| Dashboard security | `sessionStorage` + `history.replaceState` |
| CORS preflight | Runs before auth gate |
| CSP fix | Inline dashboard scripts work again |

### 🖥️ Full REST API

**Core:** `GET /` — dashboard · `GET /ping` — health · `GET /version` · `GET /setup-status` · `POST /setup`

**Desktop Control:** `POST /mouse/move` · `POST /mouse/click` · `POST /mouse/drag` · `POST /mouse/scroll` · `POST /key/type` · `POST /key/press` · `POST /chain`

**Screenshots:** `GET /screen` · `GET /screen/base64` · `GET /screen/jpeg` · `GET /screen/fresh` · `POST /ocr/find` · `GET /describe`

**UIA:** `GET /uia/tree` · `GET /uia/find/<name>` · `POST /uia/click` · `POST /uia/element/find` · `POST /uia/element/click-by-name`

**File Ops:** `POST /file/list` · `POST /file/read` · `POST /file/write` · `POST /file/delete` (needs `confirm: true`)

**Browser:** `POST /browser/navigate` · `POST /browser/click` · `POST /browser/fill` · `POST /browser/extract` · `POST /browser/screenshot`

**Agent Gateway:** `GET /agent/status` · `POST /agent/exec` · `POST /agent/audit` · `POST /agent/plan` · `POST /agent/implement` · `GET /agent/logs`

**Other:** `POST /voice/toggle` · `POST /toast/show` · `POST /google/gmail/send` · `POST /tunnel/start` · `POST /emergency/stop`

---

## 🏗 Architecture (v7.8)

```
hermes_coagent.py          — Main server (auth, CORS, health, watchdog)
├── routes_mouse.py        — Mouse/keyboard/chain/smart click
├── routes_ocr.py          — Screenshots/OCR/FallbackChain (5 methods)
├── routes_uia.py          — UIA tree/SOM/element find
├── routes_file.py         — File ops/app launch/power
├── routes_media.py        — Wallpaper/clipboard/macros/scheduler
├── routes_process.py      — Process management
├── routes_voice.py        — Voice commands
├── routes_cua.py          — Cua Driver (37 tools)
├── routes_copilot.py      — AI Co-Pilot
├── routes_bypass.py       — Prompt bypass toolkit (9 endpoints)
├── routes_agent.py        — 🆕 Agent Gateway (6 endpoints)
├── routes_toast.py        — Toast notifications
├── routes_browser.py      — Playwright browser automation
├── routes_google.py       — Google Workspace (Gmail + Calendar)
├── routes_streak.py       — SSE screen streaming
|__ and more in AGENTS.md
├── shared.py              — Shared utilities
├── auth.py                — Bearer token auth
├── coagent_watchdog.ps1   — Self-healing watchdog
├── AGENTS.md              — AI onboarding guide (read this!)
```

---

## 🔐 Security

| Flag | Effect |
|------|--------|
| `--secure` | Enable Bearer auth using `.token` or first-time setup |
| `--token=KEY` | Enable Bearer auth with explicit token |
| `HERMES_COAGENT_TOKEN` | Enable Bearer auth from env var |
| `--allow-external` | Bind `0.0.0.0` for LAN (requires auth) |

**All endpoints require Bearer auth** except: `/`, `/health`, `/ping`, `/version`, `/favicon.ico`, `/setup`, `/setup-status`.

Token file `.token` is gitignored. Dashboard uses `sessionStorage` (cleared on tab close). No hardcoded secrets in source.

---

## 🔧 Requirements

- **Windows 10/11**
- **Python 3.8+**
- **Core:** `flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss psutil`
- **Optional:** `dxcam` (GPU screenshots), `playwright` (browser), `google-api-python-client` + `google-auth-oauthlib` (Google), `win11toast` (notifications)

---

## 🤖 How AI Agents Use This

See `AGENTS.md` for the full AI onboarding guide. Key patterns:

1. **Authenticate:** Send `Authorization: Bearer TOKEN` on every request
2. **See the screen:** `GET /screen/base64` → decode → analyze → pick coordinates
3. **Click:** `POST /mouse/click {"x":960,"y":540}`
4. **Read UI:** `GET /uia/tree` → find element by name → `POST /uia/click {"name":"OK"}`
5. **Automate:** `POST /chain` with batched mouse/keyboard actions
6. **Self-heal:** `GET /health` to verify, `GET /watchdog/status` for uptime

---

## 📄 License

MIT — see [LICENSE](LICENSE)
