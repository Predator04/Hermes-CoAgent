# Hermes CoAgent

[![CI — Syntax Check & Compile](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Predator04/Hermes-CoAgent/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/Predator04/Hermes-CoAgent?style=social)](https://github.com/Predator04/Hermes-CoAgent/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

**Local Windows desktop automation REST API server** — gives AI agents full control over mouse, keyboard, screen, windows, processes, browsers, and more through a single Flask HTTP API. Built for Hermes Agent but works with any LLM orchestration layer.

> 📱 **Android companion:** drive a phone the same way (tap/swipe/type/navigate + UI-tree vision) — [Hermes CoAgent Android](https://github.com/Predator04/Hermes-CoAgent-Android)

---

## Quick Start

```bash
git clone https://github.com/Predator04/Hermes-CoAgent.git
cd Hermes-CoAgent
pip install -r requirements.txt
python hermes_coagent.py --secure --allow-external
```

**`--secure`** auto-generates a Bearer token in `.token`. **`--allow-external`** binds to `0.0.0.0:9123` for WSL/remote access.

```bash
# Verify it's alive
curl http://127.0.0.1:9123/ping

# View version & capabilities
curl http://127.0.0.1:9123/version

# Dashboard
open http://127.0.0.1:9123/dashboard

# Full API catalog
curl http://127.0.0.1:9123/help
```

## Features

| Category | Capabilities |
|---|---|
| **Desktop Control** | Mouse move/click/drag/scroll, keyboard typing, hotkeys, action chains, background SendInput |
| **Screen Intelligence** | JPEG/PNG/base64 screenshots, OCR, text finding, scene object model overlays, DXGI capture |
| **UI Automation** | UIA tree, element lookup by name/type/automationId, window targeting, SOM overlays |
| **Browser Automation** | Thread-owned Patchright/Playwright sessions — navigate, click, type, extract, screenshot, DOM snapshots |
| **System Control** | Process list/start/kill, window list/activate/move/resize, clipboard, power management, volume, brightness |
| **AI Agent Gateway** | Invoke Codex, Claude, Gemini, OpenCode CLIs — `/agent/exec` and `/agent/exec-to-telegram` |
| **Goal Runner** | Multi-step goal execution with SSE progress, timeline cards, activity log, batch plan-execute |
| **Stealth Browser** | 13 anti-detection patches, Cloudflare bypass, persistent profiles, fingerprint randomization |
| **MCP Bridge** | JSON-RPC MCP server auto-discovers 60+ CoAgent endpoints as tools. Config generator for Claude Desktop, Cursor, Hermes |
| **MCP Client Mode** | Generic MCP client — connect out to external MCP servers (stdio + HTTP/SSE), aggregate their tools into CoAgent as a single hub |
| **Agent Skills Loader** | Progressive-disclosure SKILL.md loader — inject skill bodies into `/agent/exec` prompts on demand |
| **Companion Extension** | Long-poll relay driving the user's *real* browser with real sessions via an MV3 extension |
| **Governance** | App/URL allowlist+denylist, per-hour/per-goal action budgets, secret/PII redaction (active in logs + OCR) |
| **One-Click Deploy** | Full pipeline: deps → token → launch. Optional ngrok tunnel for NAT/cellular |
| **Reliability** | Watchdog, endpoint health tracking, self-healing checks, dependency helper, memory leak watchdog |
| **Automation Kits** | Scheduled recipes, macro recording, GIF recording, undo/redo, visual diff, smart element finder |
| **Remote Access** | Web dashboard, mobile remote view, SSE screen stream, SMS bridge, phone bridge via ADB |
| **Security** | Bearer auth, CSRF protection, rate limiting, CORS, secret file ignores, private URL blocking |

## Authentication

| Method | Description |
|---|---|
| `--secure` | Enable auth using `./.token`, auto-created on first launch |
| `--token=KEY` | Start with explicit token and save to `./.token` |
| `HERMES_COAGENT_TOKEN` | Read token from environment variable |
| `--allow-external` | Bind to `0.0.0.0` (requires `--secure`) |

```bash
curl http://127.0.0.1:9123/screen/base64 \
  -H "Authorization: Bearer $(cat .token)"
```

The `.token` file is gitignored. Do not expose port 9123 to untrusted networks without a reverse proxy.

> **⚠️ Auth is opt-in.** Without `--secure` the server runs **unauthenticated** — anyone who can reach the port gets full desktop control. `--allow-external` (bind to `0.0.0.0`) is **hard-refused unless `--secure` is also passed**. For any network-exposed deployment, always run with `--secure`.

## API Reference

`GET /help` returns the full endpoint catalog as JSON. `GET /help?format=text` for terminal output.

| Method | Path | Description |
|---|---|---|
| `GET` | `/ping` | Liveness check |
| `GET` | `/version` | Version, build, feature list |
| `GET` | `/help` | Full API documentation |
| `GET` | `/dashboard` | Operator web dashboard |
| `GET` | `/metrics` | Prometheus-style metrics |
| `GET` | `/screen/base64` | Screenshot as base64 JPEG |
| `GET` | `/screen/png` | Screenshot as PNG |
| `POST` | `/mouse/move` | Move mouse to coordinates |
| `POST` | `/mouse/click` | Click at coordinates |
| `POST` | `/mouse/scroll` | Scroll at position |
| `POST` | `/mouse/drag` | Click and drag |
| `POST` | `/key/type` | Type text |
| `POST` | `/key/hotkey` | Send key combination |
| `GET` | `/uia/tree` | UIA accessibility tree |
| `POST` | `/uia/find` | Find UI element |
| `POST` | `/uia/click` | Click UI element |
| `GET` | `/windows/list` | List all windows |
| `POST` | `/windows/activate` | Focus a window |
| `GET` | `/process/list` | List running processes |
| `POST` | `/process/start` | Launch a process |
| `POST` | `/process/kill` | Kill a process |
| `POST` | `/power/sleep` | Put system to sleep |
| `POST` | `/power/shutdown` | Shut down system |
| `GET` | `/clipboard` | Read clipboard |
| `POST` | `/clipboard` | Write clipboard |
| `POST` | `/agent/exec` | Run installed AI agent CLI |
| `POST` | `/agent/exec-to-telegram` | Run agent, deliver to Telegram |
| `POST` | `/goal-runner/start` | Start goal with progress tracking |
| `GET` | `/goal-runner/status` | Live goal progress (SSE) |
| `POST` | `/browser/open` | Open browser session |
| `POST` | `/browser/navigate/<id>` | Navigate URL in session |
| `POST` | `/browser/click/<id>` | Click element in session |
| `POST` | `/browser/type/<id>` | Type text in session |
| `POST` | `/browser/extract/<id>` | Extract page content |
| `GET` | `/browser/screenshot/<id>` | Screenshot browser session |
| `POST` | `/stealth/navigate` | Undetectable browser navigation |
| `GET` | `/stealth/health` | Browser detectability self-test |
| `GET` | `/mcp/config` | Generate MCP client configs |
| `POST` | `/mcp/client/register` | Register an external MCP server (stdio/HTTP) |
| `GET` | `/mcp/client/servers` | List registered MCP servers |
| `GET` | `/mcp/client/tools` | List all tools across MCP servers |
| `POST` | `/mcp/client/call` | Call a tool on a registered MCP server |
| `GET` | `/skills/list` | List loaded agent skills |
| `GET` | `/skills/<name>` | Get a skill's body + bundled files |
| `POST` | `/skills/reload` | Rescan the skills directory |
| `GET` | `/governance/policy` | Read the governance policy |
| `POST` | `/governance/policy` | Update policy (allowlist/denylist/budgets) |
| `GET` | `/governance/status` | Governance + budget usage status |
| `GET` | `/governance/audit` | Blocked-action audit log |
| `POST` | `/governance/redact` | Redact secrets/PII from text |
| `POST` | `/browser/companion/command` | Send a command to the companion extension |
| `GET` | `/browser/companion/poll` | Extension long-poll for pending commands |
| `POST` | `/browser/companion/result` | Extension posts a command result |
| `POST` | `/deploy/oneclick` | One-click deploy pipeline |
| `POST` | `/deploy/ngrok` | Start ngrok tunnel |
| `POST` | `/recipes/run` | Execute automation recipe |
| `GET` | `/reminders/list` | List scheduled reminders |

## File Structure

```
Hermes-CoAgent/
├── VERSION                    # Single source of truth for version
├── scripts/                   # Standalone utility scripts
│   ├── bump_version.py        # Version bump utility
│   ├── test_compile.py        # Quick syntax check
│   ├── remote_agent.py        # Lightweight remote desktop agent
│   ├── screenshot_relay.py    # Screenshot relay for session isolation
│   ├── cua_mcp_bridge.py      # MCP stdio bridge for WSL
│   └── oauth_server.py        # OAuth callback server
├── shared.py                  # Shared utilities, SSE helpers, logging
├── auth.py                    # Bearer auth + CSRF protection
├── uia_engine.py              # Windows UI Automation engine
├── tray_icon.py               # Windows system tray with Dashboard/Settings
├── requirements.txt           # Python dependencies
├── setup.py                   # Pip-installable package definition
├── pytest.ini                 # Test configuration
├── dashboard.html             # Operator web dashboard
├── coagent_icon.ico           # Application icon
├── coagent_installer.nsi      # NSIS installer script
├── install_coagent.py         # One-click installer
├── install_coagent.bat        # Batch installer launcher
├── launch_all.ps1             # PowerShell Session 1 launcher
├── start_coagent.bat          # Double-click launcher
├── routes_*.py                # Modular route handlers (see below)
├── tests/                     # Test suite
├── AGENTS.md                  # AI agent configuration
├── CONTRIBUTING.md            # Contribution guide
├── SECURITY.md                # Security policy
├── LICENSE                    # MIT license
└── .gitignore
```

### Route Modules

| Module | Purpose |
|---|---|
| `routes_agent.py` | AI agent gateway — Codex, Claude, Gemini, OpenCode |
| `routes_browser.py` | Playwright browser control (single-session) |
| `routes_browser_final.py` | Thread-owned browser sessions |
| `routes_buddy.py` | Desktop Buddy integration |
| `routes_bypass.py` | AI bypass toolkit |
| `routes_config.py` | Config backup and rollback |
| `routes_copilot.py` | Pattern-based AI co-pilot |
| `routes_copilot_enhanced.py` | Multi-step goal execution (SSE) |
| `routes_cua.py` | Cua Driver integration |
| `routes_dashboard.py` | Real-time HTML dashboard |
| `routes_deploy.py` | One-click deploy pipeline |
| `routes_deps.py` | Dependency management |
| `routes_diff.py` | Visual screenshot diffing |
| `routes_docs.py` | OpenAPI spec + Swagger UI |
| `routes_file.py` | File ops, app launch, power |
| `routes_finder.py` | OCR-backed element finder |
| `routes_git.py` | Git backup, commit, rollback |
| `routes_google.py` | Google Workspace bridge |
| `routes_healer.py` | Self-healing health monitor |
| `routes_help.py` | API documentation endpoint |
| `routes_hud.py` | Transparent desktop HUD |
| `routes_logs.py` | Log analyzer |
| `routes_mcp.py` | MCP JSON-RPC bridge |
| `routes_mcp_client.py` | MCP client mode (connect to external servers) |
| `routes_skills.py` | Agent skills loader (SKILL.md injection) |
| `routes_companion.py` | Companion browser-extension relay |
| `routes_governance.py` | Allowlist/budgets/redaction governance layer |
| `routes_media.py` | Wallpaper, scheduler, tunnel, voice |
| `routes_memory.py` | Persistent FTS5 memory |
| `routes_metrics.py` | Prometheus metrics |
| `routes_mobile.py` | Mobile remote-control page |
| `routes_mouse.py` | Mouse, keyboard, action chains |
| `routes_obsidian.py` | Obsidian vault bridge |
| `routes_ocr.py` | Screenshots, OCR, screen relay |
| `routes_palmreject.py` | Palm rejection settings |
| `routes_phone.py` | Android phone bridge (ADB) |
| `routes_plugins.py` | Hot-loadable plugin system |
| `routes_process.py` | Process listing and control |
| `routes_recipes.py` | Scheduled automation recipes |
| `routes_recorder.py` | Macro recorder |
| `routes_recorder_gif.py` | Animated GIF recorder |
| `routes_reminders.py` | Timed reminders and alerts |
| `routes_stealth_browser.py` | Undetectable browser (13 patches) |
| `routes_stream.py` | Screen streaming (SSE/WS) |
| `routes_system.py` | System info, volume, brightness |
| `routes_telegram.py` | Telegram bot relay |
| `routes_toast.py` | Windows toast notifications |
| `routes_uia.py` | UIA tree, SOM, element finding |
| `routes_undo.py` | Action undo/redo |
| `routes_updates.py` | Self-update and restart |
| `routes_voice.py` | Voice command recognition |
| `routes_webcam.py` | Webcam capture |
| `routes_webhooks.py` | Webhook registration and dispatch |
| `routes_webrtc.py` | Remote desktop MJPEG stream |
| `routes_wol.py` | Wake-on-LAN |

Plus **59 auto-route modules** (`routes_auto_*.py`) wrapping common Windows CLI tools (ipconfig, netsh, choco, winget, etc.).

## Versioning

**Single source of truth:** `VERSION` file in repo root.

```bash
# Check current version
python scripts/bump_version.py

# Bump version
python scripts/bump_version.py patch   # 8.50 → 8.51
python scripts/bump_version.py minor   # 8.50 → 9.0
python scripts/bump_version.py major   # 8.50 → 9.0.0

# Set exact version
python scripts/bump_version.py 9.0.0
```

All Python files read from `VERSION` at runtime — no hardcoded version strings to chase down. Update `VERSION`, commit, and the `/version` endpoint reflects it automatically.

## Development

```bash
# Install dev deps
pip install -r requirements.txt

# Run syntax check
python scripts/test_compile.py

# Run tests
pytest tests/ -v

# Start server
python hermes_coagent.py --secure --allow-external
```

CI runs syntax/compile checks on Python 3.11+ across Windows and Ubuntu. Windows is the production runtime for desktop-control features.

See [CHANGELOG.md](CHANGELOG.md) for release history, [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow, and [SECURITY.md](SECURITY.md) for security reporting.

## License

MIT. See [LICENSE](LICENSE).
