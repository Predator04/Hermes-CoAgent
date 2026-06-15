# Hermes CoAgent

**Ultimate Desktop Co-Pilot for Windows** — gives AI agents (Hermes, Claude, Codex, etc.) full native Windows desktop control. Screenshots, mouse/keyboard, UIA accessibility trees, OCR, window management — all local, zero API costs.

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
| **Screenshots** | Full screen capture as PNG or base64 |
| **Clipboard** | Read/write clipboard text |
| **File Operations** | List, read, write, delete files on the Windows filesystem |
| **Chain Actions** | Execute multi-step sequences atomically |
| **Emergency Stop** | Kill all input instantly via API or Ctrl+Alt+Shift |
| **Macro Recorder** | Record and replay mouse/keyboard sequences |
| **TTS** | Speak text through speakers (edge-tts) |
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
| `--secure` | Generates a random 64-char token. Prints it at startup. All endpoints require `Authorization: Bearer <token>`. |
| `--token=MYKEY` | Uses your key instead of a random one. Combine with `--secure` or use alone. |
| `--allow-external` | Binds to `0.0.0.0` (all network interfaces). **Requires `--secure` or `--token` to be safe.** |

```
# Recommended for LAN access:
python hermes_coagent.py --secure --allow-external
# Output: [Auth] Secure mode enabled — token: a1b2c3d4e5f6...7890abcd
# Clients send header: Authorization: Bearer a1b2c3d4e5f6...7890abcd
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

All endpoints are available at `http://localhost:9123/` (requires Auth header if `--secure`).

### Core

| Method | Route | Description |
|---|---|---|
| GET | `/` | Web dashboard |
| GET | `/ping` | Health check |
| GET | `/cursor/pos` | Mouse position |
| GET | `/cursor` | Alias for cursor/pos |

### Mouse
| Method | Route | Description |
|---|---|---|
| POST | `/mouse/move` | `{"x": 500, "y": 400}` |
| POST | `/mouse/click` | `{"button": "left"}` |
| POST | `/move` | Alias for mouse/move |
| POST | `/click` | Alias for mouse/click |

### Keyboard
| Method | Route | Description |
|---|---|---|
| POST | `/key/type` | `{"text": "hello"}` |
| POST | `/key/press` | `{"keys": ["ctrl", "c"]}` |
| POST | `/type` | Alias for key/type |
| POST | `/hotkey` | Alias for key/press |

### Screen
| Method | Route | Description |
|---|---|---|
| GET | `/screen` | Cached screenshot (image) |
| GET | `/screenshot` | Base64 screenshot |
| GET | `/screenshot/fresh` | Force fresh screenshot |
| GET | `/screensize` | Display resolution |

### Smart
| Method | Route | Description |
|---|---|---|
| POST | `/chain` | Multi-action sequence |
| POST | `/act` | Action + before/after screenshots |

### Find
| Method | Route | Description |
|---|---|---|
| POST | `/ocr/find` | `{"text": "Save"}` |
| GET | `/uia/tree` | Full UIA tree |
| GET | `/uia/snapshot` | Alias for uia/tree |
| POST | `/uia/click` | Click by index or name |

### Windows
| Method | Route | Description |
|---|---|---|
| GET | `/windows` | All open windows |
| POST | `/windows/activate` | `{"title": "Chrome"}` |
| POST | `/activate` | Alias for windows/activate |

### Files
| Method | Route | Description |
|---|---|---|
| POST | `/file/list` | `{"path": "C:/Users/Admin/Desktop"}` |
| POST | `/file/read` | `{"path": "C:/file.txt"}` |
| POST | `/file/write` | `{"path": "C:/file.txt", "content": "..."}` |
| POST | `/file/delete` | `{"path": "C:/file.txt"}` |

### Emergency
| Method | Route | Description |
|---|---|---|
| POST | `/emergency/stop` | Lock all input |
| POST | `/emergency/resume` | Unlock input |
| GET | `/emergency/status` | Current state |
| *(keyboard)* | `Ctrl+Alt+Shift` | Instant emergency stop |

### Other
| Method | Route | Description |
|---|---|---|
| POST | `/clipboard/set` | `{"text": "..."}` |
| GET | `/clipboard/get` | Clipboard text |
| POST | `/app/open` | `{"path": "notepad.exe"}` |
| POST | `/app/run` | `{"cmd": "dir", "timeout": 30}` |
| GET | `/monitors` | Monitor layout |
| POST | `/tts/speak` | `{"text": "hello"}` |
| GET | `/history` | Last N actions |
| POST | `/replay` | Replay last N actions |

---

## 📋 Requirements

- **OS:** Windows 10/11
- **Python:** 3.8+
- **Tesseract OCR** (optional — for OCR find feature)
- **Hermes Agent** (optional — for MCP protocol integration)

### Python Packages
```
pyautogui flask pillow pynput mss pygetwindow pyperclip
pytesseract opencv-python edge-tts psutil pywinauto
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
├── hermes_coagent.py        # Main server — Flask HTTP + input engine + all APIs
├── computer_use_mcp.py      # MCP protocol server — 26 tools for AI agents
├── uia_engine.py            # UIA accessibility tree + SOM overlay engine
├── coagent_tray.py          # System tray app (runs via pythonw.exe)
├── auth.py                  # Bearer token authentication module
├── AGENTS.md                # Instructions for AI coding agents
├── launch_all.ps1           # One-shot launcher (kill stale + start + wait)
├── send_telegram_file.ps1   # One-shot file transfer prep
├── LICENSE                  # MIT License
├── .gitignore
└── README.md
```

---

## ⚡ Performance

- **MCP startup:** ~2s with `MCP_FAST=1` (lazy imports)
- **Screenshots:** <100ms (PIL ImageGrab)
- **Actions:** 50ms gap between actions
- **UIA queries:** ~200ms with 2s cache
- **Screenshot cache:** 500ms TTL

---

## ⚠️ Disclaimer

This tool provides **full remote desktop control** to anyone who can reach the HTTP server. **Always use `--secure` when allowing network access.** The authors are not responsible for misuse.

---

## 📄 License

MIT — see [LICENSE](LICENSE)
