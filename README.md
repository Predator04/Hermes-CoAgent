# Hermes CoAgent v5.0

**Ultimate Desktop Co-Pilot for Windows** — gives AI agents (Hermes, Claude, Codex, etc.) full native Windows desktop control. Screenshots, mouse/keyboard, UIA accessibility trees, OCR, voice control, file search, wallpaper, power management — all local, zero API costs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🔥 Features

| Capability | What it does |
|---|---|
| **UIA Accessibility Tree** | Full Windows accessibility tree — find any button, label, text field by name |
| **SOM Overlays** | Numbered bounding boxes on every interactable element |
| **OCR Find** | Locate text on screen using Tesseract OCR |
| **Mouse Control** | Click, double-click, right-click, move, drag, scroll |
| **Keyboard** | Type text, press hotkeys (ctrl+c, alt+tab, etc.) |
| **Window Management** | List windows, activate by title |
| **Screenshots** | Full screen capture as PNG, JPEG, or base64 |
| **Smart Crop** | OCR a screen region, copy text to clipboard |
| **Screen Description** | OCR the whole screen, return formatted text |
| **Clipboard** | Read/write clipboard text |
| **File Operations** | List, read, write, delete files on Windows |
| **File Search** | Find files by name/glob across drives |
| **Chain Actions** | Execute multi-step sequences atomically |
| **Emergency Stop** | Kill all input instantly via API or Ctrl+Alt+Shift |
| **Macro Recorder** | Record and replay mouse/keyboard sequences |
| **TTS** | Speak text through speakers (edge-tts) |
| **Power Management** | Sleep, shutdown, restart, lock workstation |
| **Wallpaper Control** | Set, cycle, or random desktop wallpapers |
| **Voice Control** | Wake-word voice commands (click, type, scroll) |
| **AI App Launcher** | Smart launch apps by description ("open chrome to reddit") |
| **Scheduled Actions** | Cron-like timed desktop operations |
| **Monitor Layout** | Tile all visible windows in a grid |
| **System Tray** | Persistent tray icon with start/stop/emergency controls |
| **Fast Mode** | Lazy-imports heavy deps for sub-second MCP startup |
| **Auth** | Bearer token authentication (`--secure`) |
| **MCP Protocol** | Full Model Context Protocol support for Hermes Agent |

---

## 🏗 Architecture

```
                    ┌─────────────────────────────┐
                    │      AI Agent (Hermes)       │
                    │  (runs in WSL / anywhere)    │
                    └──────────┬──────────────────┘
                               │ MCP stdio protocol
                               │ (cmd.exe /c python)
                               ▼
                    ┌─────────────────────────────┐
                    │   computer_use_mcp.py       │
                    │   (MCP Server — 26 tools)   │
                    │   - Routes all calls to     │
                    │     CoAgent HTTP API        │
                    └──────────┬──────────────────┘
                               │ HTTP localhost:9123
                               ▼
        ┌─────────────────────────────────────────────┐
        │           hermes_coagent.py                  │
        │   (Flask HTTP server + input engine)         │
        │                                              │
        │  ┌────────────┐  ┌──────────┐  ┌─────────┐  │
        │  │ pyautogui  │  │pytesseract│  │ win32gui│  │
        │  │ mouse/kbd  │  │  OCR     │  │  pulse  │  │
        │  └────────────┘  └──────────┘  └─────────┘  │
        │                                              │
        │  ┌──────────────────────────────────────┐    │
        │  │        uia_engine.py                  │    │
        │  │  pywinauto — UIA tree, SOM overlay,  │    │
        │  │  background input, find-on-screen    │    │
        │  └──────────────────────────────────────┘    │
        │                                              │
        │  ┌──────────────────────────────────────┐    │
        │  │        auth.py                         │    │
        │  │  Bearer token auth — --secure / --token│    │
        │  └──────────────────────────────────────┘    │
        │                                              │
        │  ┌──────────────────────────────────────┐    │
        │  │   V5.0 NEW:                          │    │
        │  │   Power, Wallpaper, File Search,     │    │
        │  │   Voice, Smart Crop, Describe,       │    │
        │  │   Scheduler, AI Launcher, Layout     │    │
        │  └──────────────────────────────────────┘    │
        └─────────────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │    Windows Desktop │
                    │  (actual session)  │
                    └───────────────────┘
```

**Data flow:** Agent → MCP stdio → `computer_use_mcp.py` → HTTP → `hermes_coagent.py` → Windows APIs → Desktop

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install pyautogui flask pillow pynput mss pygetwindow pyperclip pytesseract opencv-python edge-tts psutil pywinauto

# 2. Start the server (DEFAULT: secure mode on localhost)
python hermes_coagent.py --secure

# 3. Open dashboard
# Open http://localhost:9123/ in your browser

# For AI agent integration (MCP mode):
python hermes_coagent.py --mcp
```

### One-shot launcher (recommended)

```powershell
powershell -File "launch_all.ps1"
```

This kills stale processes, starts CoAgent with auth, and configures MCP fast mode.

---

## 🔐 Security

**Security is always opt-in** by design for local development, but **strongly encouraged** for any network-accessible deployment.

| Flag | Behavior |
|---|---|
| _(none)_ | No auth. Binds to `127.0.0.1` (localhost only). Safe for local use. |
| `--secure` | Generates a random 64-char token. Prints it at startup. All endpoints require `Authorization: Bearer <token>` |
| `--token=MYKEY` | Uses your key instead of a random one. Combine with `--secure` or use alone. |
| `--allow-external` | Binds to `0.0.0.0` (all network interfaces). **Requires `--secure` or `--token` to be safe.** |

```bash
# Recommended for LAN access:
python hermes_coagent.py --secure --allow-external
# Output: [Auth] Secure mode enabled — token: a1b2c3d4e5f6...7890abcd
# Clients send header: Authorization: Bearer a1b2c3...abcd
```

**Emergency stop:** Press `Ctrl+Alt+Shift` anywhere to instantly kill all input. No API call needed.

---

## 🤖 MCP Integration with Hermes Agent

Add this to your `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  windows-computer-use:
    command: cmd.exe
    args:
      - /c
      - python
      - C:\Users\Admin\Desktop\Hermes CoAgent\computer_use_mcp.py
    timeout: 120
    connect_timeout: 30
    env:
      MCP_FAST: '1'
      COAGENT_URL: 'http://localhost:9123'
```

### Available MCP Tools (26 total)

- `ping` — health check
- `screenshot` — raw screenshot (base64 PNG)
- `capture(mode)` — SOM overlay, raw, or UIA tree
- `click(x, y, button)` — click at coordinates
- `click_element(index)` — click by SOM index
- `double_click(x, y)` — double click
- `right_click(x, y)` — right click
- `move_mouse(x, y)` — move to coordinates
- `type_text(text)` — type at cursor
- `press_key(keys)` — hotkey combo
- `scroll(clicks)` — scroll wheel
- `drag(x1, y1, x2, y2)` — drag action
- `get_uia_tree()` — full accessibility tree
- `list_windows()` — all open windows
- `activate_window(title)` — focus window
- `find_on_screen(text)` — UIA + OCR combined search
- `chain(actions)` — execute multiple actions atomically
- `get_monitors()` — display layout
- `get_cursor_position()` — current mouse position
- `get_coagent_status()` — server health
- `emergency_stop()` / `emergency_resume()` — kill/resume input
- `wake_screen()` — Ctrl+Alt+Del screen wake
- `launch_app(path)` — start application
- `click_by_name(name)` — click by UIA element label

---

## 📡 REST API

All endpoints at `http://localhost:9123/` (requires Auth header if `--secure`).

### Core

| Method | Route | Description |
|---|---|---|
| GET | `/` | Web dashboard |
| GET | `/dashboard2` | Alternative dashboard (SOM view) |
| GET | `/ping` | Health check |
| GET | `/settings` | Autostart status |
| POST | `/settings/autostart` | Toggle autostart on/off |
| GET | `/cursor/pos` | Mouse position |
| GET | `/cursor` | Alias |
| GET | `/monitors` | Display layout |
| GET | `/screensize` | Display resolution |
| GET | `/stats` | Server stats |

### Mouse

| Method | Route | Body |
|---|---|---|
| POST | `/mouse/move` | `{"x": 500, "y": 400}` |
| POST | `/mouse/click` | `{"button": "left"}` |
| POST | `/mouse/doubleclick` | |
| POST | `/mouse/rightclick` | |
| POST | `/mouse/drag` | `{"x1":0,"y1":0,"x2":500,"y2":400}` |
| POST | `/mouse/scroll` | `{"clicks": -3}` |
| POST | `/move` | Alias |
| POST | `/click` | Alias |
| POST | `/drag` | Alias |
| POST | `/scroll` | Alias |

### Keyboard

| Method | Route | Body |
|---|---|---|
| POST | `/key/type` | `{"text": "hello"}` |
| POST | `/key/press` | `{"keys": ["ctrl", "c"]}` |
| POST | `/type` | Alias |
| POST | `/hotkey` | Alias |

### Screen

| Method | Route | Description |
|---|---|---|
| GET | `/screen` | Cached screenshot (PNG image) |
| GET | `/screenshot` | Base64 screenshot JSON |
| GET | `/screenshot/fresh` | Force fresh screenshot |
| GET | `/screenshot/cached` | Cached version |
| GET | `/screen/base64` | Base64 screenshot |
| GET | `/screen/diagnose` | Diagnostic info |

### Smart Actions

| Method | Route | Body |
|---|---|---|
| POST | `/chain` | `{"actions": [...]}` |
| POST | `/act` | Action + before/after screenshots |

### Find

| Method | Route | Body |
|---|---|---|
| POST | `/ocr/find` | `{"text": "Save"}` |
| POST | `/visual/find` | `{"template_path": "C:/img.png", "confidence": 0.8}` |
| GET | `/uia/tree` | Full UIA tree |
| GET | `/uia/snapshot` | UIA snapshot |
| POST | `/uia/click` | `{"index": 3}` or `{"name": "..."}` |
| POST | `/uia/find-combined` | UIA + OCR combined |
| GET | `/uia/diag` | UIA diagnostic |
| GET | `/som` | SOM overlay screenshot |
| GET | `/som/screenshot` | SOM overlay |
| GET | `/som/image` | SOM image |

### Windows

| Method | Route | Body |
|---|---|---|
| GET | `/windows` | All open windows |
| POST | `/windows/activate` | `{"title": "Chrome"}` |
| POST | `/activate` | Alias |

### Files

| Method | Route | Body |
|---|---|---|
| POST | `/file/list` | `{"path": "C:/Users/..."}` |
| POST | `/file/read` | `{"path": "C:/file.txt"}` |
| POST | `/file/write` | `{"path": "...", "content": "..."}` |
| POST | `/file/delete` | `{"path": "..."}` |

### V5.0 — Power

| Method | Route | Description |
|---|---|---|
| POST | `/power/sleep` | Put PC to sleep |
| POST | `/power/shutdown` | Shutdown (body: `{timeout: 30}`) |
| POST | `/power/restart` | Restart |
| POST | `/power/lock` | Lock workstation |
| POST | `/power/cancel` | Cancel pending shutdown |

### V5.0 — Wallpaper

| Method | Route | Body |
|---|---|---|
| POST | `/wallpaper/set` | `{path: "C:/img.jpg"}` |
| POST | `/wallpaper/cycle` | `{folder: "C:/wallpapers"}` |
| POST | `/wallpaper/random` | `{folder: "C:/wallpapers"}` |

### V5.0 — Search & OCR

| Method | Route | Body |
|---|---|---|
| POST | `/search/files` | `{pattern: "*.pdf", path: "C:/", limit: 50}` |
| POST | `/crop` | `{region: [x,y,w,h]}` (optional — OCR screen) |
| GET | `/describe` | OCR the whole screen |

### V5.0 — Scheduler

| Method | Route | Body |
|---|---|---|
| GET | `/scheduler/list` | List all scheduled actions |
| POST | `/scheduler/add` | `{name, cron, action}` |
| POST | `/scheduler/remove` | `{name}` |
| POST | `/scheduler/run` | `{name}` |

### V5.0 — Voice & AI

| Method | Route | Body |
|---|---|---|
| POST | `/voice/toggle` | `{enable: true/false}` |
| POST | `/launch/ai` | `{query: "open chrome to reddit"}` |
| POST | `/monitors/layout` | `{layout: "grid"}` |

### Emergency

| Method | Route | Description |
|---|---|---|
| POST | `/emergency/stop` | Lock all input |
| POST | `/emergency/resume` | Unlock input |
| GET | `/emergency/status` | Current state |
| *(keyboard)* | `Ctrl+Alt+Shift` | Instant emergency stop |

### Other

| Method | Route | Body |
|---|---|---|
| POST | `/clipboard/set` | `{"text": "..."}` |
| GET | `/clipboard/get` | Clipboard text |
| POST | `/app/open` | `{"path": "notepad.exe"}` |
| POST | `/app/run` | `{"cmd": "dir", "timeout": 30}` |
| POST | `/tts/speak` | `{"text": "hello"}` |
| GET | `/history` | Last N actions |
| POST | `/replay` | Replay last N actions |
| GET | `/events` | SSE event stream |
| GET | `/logs` | Server logs |
| POST | `/tunnel/start` | Start Cloudflare tunnel |
| POST | `/tunnel/stop` | Stop tunnel |
| GET | `/tunnel/status` | Tunnel status |
| POST | `/macro/list` | List macros |
| POST | `/macro/record` | `{name: "..."}` |
| POST | `/macro/run` | `{name: "..."}` |
| POST | `/macro/delete` | `{name: "..."}` |
| POST | `/input/send` | Background key send |

---

## 📋 Requirements

- **OS:** Windows 10/11
- **Python:** 3.8+
- **Tesseract OCR** (optional — for OCR find/crop/describe features)
- **SpeechRecognition** (optional — for voice control)
- **Hermes Agent** (optional — for MCP protocol integration)

### Python Packages
```
pyautogui flask pillow pynput mss pygetwindow pyperclip
pytesseract opencv-python edge-tts psutil pywinauto
SpeechRecognition  # optional — voice control
pygetwindow        # optional — monitor layout
```

---

## 🖥️ CLI Reference

```
usage: hermes_coagent.py [port] [options]

positional arguments:
  port                  HTTP server port (default: 9123)

options:
  --secure              Enable Bearer token auth (generates random token)
  --token=KEY           Use specific auth token (implies --secure)
  --allow-external      Bind to 0.0.0.0 (all interfaces, not just localhost)
  --mcp                 Run in MCP stdin/stdout protocol mode
  --http                Run HTTP SSE MCP server (computer_use_mcp.py)
  --test                Run self-test and exit
  --fast                Lazy-load heavy imports (MCP mode)

environment variables:
  HERMES_COAGENT_TOKEN  Auth token (alternative to --token)
  MCP_FAST=1            Enable fast mode (env var for MCP)
  COAGENT_URL           CoAgent HTTP URL (default: http://localhost:9123)
```

---

## 📁 Project Structure

```
Hermes-CoAgent/
├── hermes_coagent.py        # Main server — 2000+ lines, all APIs + dashboard
├── computer_use_mcp.py      # MCP protocol server — 26 tools for AI agents
├── uia_engine.py            # UIA accessibility tree + SOM overlay engine
├── coagent_tray.py          # System tray app (runs via pythonw.exe)
├── auth.py                  # Bearer token authentication module
├── AGENTS.md                # Instructions for AI coding agents
├── launch_all.ps1           # One-shot launcher (kill stale + start + wait)
├── send_telegram_file.ps1   # One-shot file transfer prep
├── create_coagent_task.ps1  # Scheduled task installer for Session 1
├── send_pf.py               # File transfer automation via pyautogui
├── patch_coagent_v5.py      # V5.0 feature updater
├── LICENSE                  # MIT License
├── .gitignore
└── README.md
```

---

## ⚡ Performance

- **MCP startup:** ~2s with `MCP_FAST=1` (lazy imports)
- **Screenshots:** <100ms (PIL ImageGrab)
- **JPEG SOM overlays:** ~50ms (q85 JPEG, 3x faster than PNG)
- **Actions:** 20ms gap between actions (chain mode)
- **UIA queries:** <100ms with synchronous cached desktop
- **UIA cache:** 300ms TTL, auto-invalidated on desktop changes
- **Batch chain:** 5 actions in ~150ms (single HTTP POST)
- **Direct SOM in MCP:** ~80ms (in-process, no HTTP round-trip)

---

## 🔧 Troubleshooting

### UIA returns 0 elements / empty SOM
The server may be running in Session 0 (non-interactive). Verify:
- Screenshot <20KB = virtual display (Session 0)
- Screenshot >100KB = real desktop (Session 1)
- Run via scheduled task with `-LogonType Interactive`

### Voice control not working
```
pip install SpeechRecognition pyaudio
```

### Wallpaper / Power buttons not doing anything
These features require Windows APIs that work from any session. Check the server log for errors.

### "App not installed" on Android
Telegram bot API truncates files >50MB. Use Catbox URL or desktop drag-drop via CoAgent.

---

## ⚠️ Disclaimer

This tool provides **full remote desktop control** to anyone who can reach the HTTP server. **Always use `--secure` when allowing network access.** The authors are not responsible for misuse.

---

## 📄 License

MIT — see [LICENSE](LICENSE)
