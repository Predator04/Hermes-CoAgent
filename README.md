# Hermes CoAgent v8.2

[![CI — Syntax Check & Compile](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/Predator04/Hermes-CoAgent?style=social)](https://github.com/Predator04/Hermes-CoAgent/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

Hermes CoAgent is a **local Windows desktop automation REST API server** for AI agents and operator dashboards. It controls mouse, keyboard, screenshots, OCR, UI Automation, browser sessions, processes, windows, files, notifications, mobile remote control, and AI agent gateway workflows — all from a single Flask service.

Key highlights in v8.2:
- 🚀 **One-click deploy** — `/deploy/oneclick` installs, generates token, launches CoAgent. Optional ngrok for NAT/cellular.
- 🔍 **Stealth browser engine** — 13 anti-detection patches, Cloudflare bypass, persistent profiles, self-test scoring
- 🔌 **MCP server bridge** — Full JSON-RPC MCP server. Auto-discovers 60+ CoAgent endpoints as MCP tools. `/mcp/config` generates configs for Claude Desktop, Cursor, Hermes.

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
| 🚀 One-click deploy | Full pipeline: deps → token → launch. Optional ngrok for NAT/cellular |
| 🔍 Stealth browser | 13 anti-detection patches, Cloudflare bypass, persistent profiles, self-test |
| 🔌 MCP bridge | Full JSON-RPC MCP server. Auto-discovers routes as tools. Config generator |
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
| `POST` | `/deploy/oneclick` | One-click deploy: deps → token → launch |
| `POST` | `/stealth/navigate` | Undetectable browser navigation |
| `GET`  | `/stealth/health` | Browser detectability self-test |
| `GET`  | `/mcp/config` | Generate MCP client configs |
| `GET` | `/screen/relay/health` | Screenshot relay health check |

## File Manifest

The codebase is organized into a main server file, shared utilities, modular route handlers, a UI Automation engine, support utilities, test files, and documentation.

### Core Server

| File | Lines | Purpose |
|---|---|---|
| `hermes_coagent.py` | 1111 | Main entry point — registers all route modules and starts Flask/MCP server |

### Shared Utilities

| File | Lines | Purpose |
|---|---|---|
| `auth.py` | 340 | Token-based Bearer auth + CSRF protection |
| `shared.py` | 553 | Common helpers: logging, JSON body parsing, path sanitization, SSE helpers |
| `shared_fallbacks.py` | 43 | Fallback method chain system — try operations in order until one succeeds |
| `uia_engine.py` | 1029 | Windows UI Automation tree, SOM overlays, background SendInput |

### Route Modules (Python files in root)

| File | Lines | Purpose |
|---|---|---|
| `routes_agent.py` | 1840 | Agent gateway — invoke allowlisted local AI CLIs (Codex, Claude, Gemini, OpenCode) |
| `routes_browser.py` | 326 | Patchright/Playwright browser control (window-level) |
| `routes_browser_final.py` | 669 | Thread-owned browser automation sessions |
| `routes_buddy.py` | 163 | Ember Desktop Buddy integration |
| `routes_bypass.py` | 685 | AI bypass toolkit — prompt encoding, prefill generation, model routing |
| `routes_config.py` | 140 | Config backup and rollback |
| `routes_copilot.py` | 461 | Pattern-based AI co-pilot actions |
| `routes_copilot_enhanced.py` | 1521 | Multi-step goal execution with SSE progress |
| `routes_cua.py` | 93 | Cua Driver desktop automation integration |
| `routes_dashboard.py` | 71 | Real-time HTML operator dashboard |
| `routes_deps.py` | 252 | Dependency inspection and pip installation |
| `routes_deploy.py` | 582 | One-click deploy pipeline — install, token gen, launch, optional ngrok |
| `routes_diff.py` | 218 | Before/after screenshot diffing |
| `routes_docs.py` | 581 | OpenAPI spec and Swagger UI |
| `routes_file.py` | 180 | File operations, app launching, power management |
| `routes_finder.py` | 346 | OCR-backed smart element finder |
| `routes_git.py` | 323 | Git backup, commit, push, and rollback |
| `routes_google.py` | 265 | Google Workspace (Gmail, Calendar, Drive) API bridge |
| `routes_healer.py` | 474 | Self-healing health monitor and auto-recovery |
| `routes_help.py` | 134 | System help and API documentation |
| `routes_hud.py` | 494 | Transparent desktop HUD overlay |
| `routes_logs.py` | 112 | Log analyzer with counters and patterns |
| `routes_mcp.py` | 745 | MCP JSON-RPC bridge for CoAgent routes |
| `routes_media.py` | 821 | Wallpaper, windows, clipboard, scheduler, macro, tunnel, voice, misc |
| `routes_memory.py` | 531 | Persistent cross-session memory via SQLite FTS5 |
| `routes_metrics.py` | 263 | Prometheus-style metrics endpoint |
| `routes_mobile.py` | 310 | Mobile remote-control page and touch translation |
| `routes_mouse.py` | 383 | Mouse, keyboard, input, and action chains |
| `routes_obsidian.py` | 181 | Obsidian vault bridge |
| `routes_ocr.py` | 709 | Screenshots, OCR, crop, describe, screen relay |
| `routes_palmreject.py` | 181 | Palm and broad-touch rejection settings |
| `routes_phone.py` | 175 | Android phone bridge via ADB |
| `routes_plugins.py` | 263 | Hot-loadable plugin system |
| `routes_process.py` | 360 | Process listing, control, and resource monitoring |
| `routes_recipes.py` | 872 | Scheduled multi-step automation recipes |
| `routes_recorder.py` | 530 | Keyboard and mouse macro recorder |
| `routes_recorder_gif.py` | 267 | Animated GIF desktop session recorder |
| `routes_reminders.py` | 454 | Timed reminders and push alerts |
| `routes_stealth_browser.py` | 709 | Undetectable Playwright browser — 13 anti-detection patches, CF bypass |
| `routes_stream.py` | 165 | Screen streaming for WebSocket/SSE clients |
| `routes_telegram.py` | 445 | Telegram bot relay for Codex output delivery |
| `routes_toast.py` | 167 | Windows toast notifications |
| `routes_uia.py` | 616 | UIA accessibility tree, SOM overlay, element finding |
| `routes_undo.py` | 213 | Action history tracking and undo |
| `routes_updates.py` | 261 | Self-update and restart |
| `routes_v63.py` | 107 | v7.3 feature routes: cursor overlay, recording, stabilization |
| `routes_voice.py` | 277 | Voice command recognition and execution |
| `routes_webhooks.py` | 229 | Webhook registration and async dispatch |
| `routes_webrtc.py` | 97 | Remote desktop MJPEG stream and WebSocket frames |
| `routes_wol.py` | 145 | Wake-on-LAN |

### Support Utilities

| File | Lines | Purpose |
|---|---|---|
| `browser_automation.py` | 279 | Undetectable browser launch via patchright |
| `cua_mcp_bridge.py` | 122 | Transparent stdio bridge for cua-driver MCP from WSL |
| `screenshot_relay.py` | 217 | Lightweight screenshot server for interactive desktop session |
| `tray_icon.py` | 813 | Windows system tray icon with Dashboard/Settings/Health menu |
| `test_tray.py` | 25 | Quick pystray import and basic test |
| `setup.py` | 52 | Pip-installable package metadata |
| `launch_all.ps1` | — | PowerShell launcher — starts server, relay, and tray on Session 1 |
| `start_coagent.bat` | — | Batch file launcher for windows double-click |

### Test Suite

| File | Lines | Purpose |
|---|---|---|
| `tests/test_agent.py` | 98 | Agent gateway route tests |
| `tests/test_bypass.py` | 217 | Bypass toolset route tests |
| `tests/test_copilot_enhanced.py` | 164 | Enhanced copilot goal route tests |
| `tests/test_hud.py` | 95 | HUD overlay route tests |
| `tests/test_launch.py` | 93 | Process launch control tests |
| `tests/test_memory.py` | 75 | Cross-session memory route tests |
| `tests/test_recipes.py` | 107 | Scheduled recipe tests |
| `tests/test_reminders.py` | 80 | Reminder and alert tests |
| `tests/test_screenshot_relay.py` | 58 | Screenshot relay tests |
| `tests/test_shared.py` | 54 | Shared utility tests |
| `tests/test_uia.py` | 128 | UIA engine and element-finding tests |
| `tests/test_tray.py` | — | Tray icon test (same as root test_tray.py) |

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
