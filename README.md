# Hermes CoAgent v8.1

[![CI — Syntax Check & Compile](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/Predator04/Hermes-CoAgent?style=social)](https://github.com/Predator04/Hermes-CoAgent/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

Hermes CoAgent is a **local Windows desktop automation REST API server** for AI agents and operator dashboards. It controls mouse, keyboard, screenshots, OCR, UI Automation, browser sessions, processes, windows, files, notifications, mobile remote control, and AI agent gateway workflows — all from a single Flask service.

Key highlights in v8.1:
- 🖥️ **Goal Runner UI** — progress bars, live duration ticker, SSE events, timeline cards, activity log
- 🔒 **Single-instance lock** — PID + port + mutex prevents duplicate servers
- 📸 **Screenshot relay** — zero-flash PIL.ImageGrab from Session 1, ~30ms local
- 🧪 **79-unit test suite** — comprehensive coverage across all modules
- 🚀 **Standalone tray binary** — compiled CoAgentTray.exe with full system tray menu

## Install

```bash
git clone https://github.com/Predator04/Hermes-CoAgent.git
cd Hermes-CoAgent
python -m pip install -r requirements.txt
python hermes_coagent.py --secure
```

`--secure` reads `./.token` or creates one automatically with a 64-character bearer token.

## Quickstart

```bash
# Start the server
python hermes_coagent.py --secure

# Confirm it is alive
curl http://127.0.0.1:9123/ping

# View capabilities
curl http://127.0.0.1:9123/version

# Move and click the mouse
curl -X POST http://127.0.0.1:9123/mouse/move \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

curl -X POST http://127.0.0.1:9123/mouse/click \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540,"button":"left"}'

# Get a screenshot
curl http://127.0.0.1:9123/screen/base64 \
  -H "Authorization: Bearer $TOKEN"
```

Open the dashboard at `http://127.0.0.1:9123/dashboard`. Full API documentation at `http://127.0.0.1:9123/help`.

## Features

| Area | What Hermes CoAgent exposes |
|---|---|
| 🖱️ Desktop control | Mouse move/click/drag/scroll, keyboard typing, hotkeys, action chains |
| 📸 Screen intelligence | JPEG/base64 screenshots, OCR, text finding, scene object model overlays |
| 🏗️ UI Automation | UIA trees, element lookup, element-indexed actions, window targeting |
| 🌐 Browser automation | Playwright-backed navigation, click, fill, extract, screenshot endpoints |
| ⚙️ System control | Process list/start/kill, window list/activate/move/resize, clipboard, power |
| 🤖 AI workflows | Copilot goal runner, agent gateway for Codex/Claude/Gemini/OpenCode CLIs |
| 🧩 Automation kits | Scheduled recipes, macro recording, GIF recording, undo, visual diff |
| 🩺 Reliability | Watchdog, endpoint health tracking, self-healing checks, dependency helper |
| 📱 Remote UI | Web dashboard, mobile remote view, SSE screen stream, notifications |
| 🎯 Goal Runner | Progress bars, live duration ticker, SSE events, timeline cards, activity log |
| 🔐 Local security | Bearer auth, CSRF helpers, rate limiting, local CORS, secret file ignores |

## Authentication

Run with `--secure` for bearer-token auth:

```bash
python hermes_coagent.py --secure
```

On first secure launch, Hermes creates `./.token` with `secrets.token_hex(32)`. Send it on protected requests:

```bash
curl http://127.0.0.1:9123/agent/status \
  -H "Authorization: Bearer $TOKEN"
```

| Option | Behavior |
|---|---|
| `--secure` | Enable auth using `./.token`, creating it if missing |
| `--token=KEY` | Start with an explicit token and save it locally |
| `HERMES_COAGENT_TOKEN` | Use a token from the environment |
| `--allow-external` | Bind to `0.0.0.0`; requires auth |

The token file is ignored by git. Do not expose port `9123` to untrusted networks.

## API Docs

`GET /help` returns the full endpoint catalog as JSON. `GET /help?format=text` for terminal-friendly output.

Key endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/ping` | Liveness check |
| `GET` | `/version` | Version, modules, feature list |
| `GET` | `/dashboard` | Operator dashboard |
| `POST` | `/goal-runner/start` | Start a goal with progress tracking |
| `GET` | `/goal-runner/status` | Live goal progress via SSE |
| `POST` | `/mouse/click` | Click at screen coordinates |
| `POST` | `/key/type` | Type text |
| `GET` | `/uia/tree` | Accessibility tree |
| `POST` | `/agent/exec` | Run an installed agent CLI |
| `GET` | `/screen/relay/health` | Screenshot relay health check |

## Launch on Windows

For WSL or remote access, the recommended launch method:

```powershell
# Launch on Session 1 (interactive desktop)
C:\Users\Admin\Desktop\Hermes CoAgent\launch_all.ps1
```

This starts the server on `0.0.0.0:9123` with `--secure --allow-external`.

## Development

```bash
python -m pip install -r requirements.txt
python hermes_coagent.py --secure
```

CI runs syntax/compile checks on Python 3.11 and 3.12 across Windows and Ubuntu. Windows is the production runtime for desktop-control features.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow and [SECURITY.md](SECURITY.md) for security reporting.

## License

MIT. See [LICENSE](LICENSE).
