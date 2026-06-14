# Hermes CoAgent

**Ultimate Desktop Co-Pilot for Windows** — control your PC from any browser, chat app, or AI agent. Runs alongside you (150ms burst-mode input, no fighting for your mouse/keyboard).

## Features

- **Web Dashboard** — live screen preview + clickable coordinate map + full controls in browser
- **CoPilot Mode** — fire-and-forget input, 150ms cooldown, auto-detect user activity
- **MCP Mode** — JSON-RPC stdin/stdout protocol for native AI agent integration
- **OCR Find** — locate buttons and text on screen by label, get coordinates
- **Visual Search** — find images on screen via OpenCV template matching
- **TTS** — speak through speakers with edge-tts
- **Keyboard Watchdog** — press `Ctrl+Alt+Shift` for instant emergency stop (no API call needed)
- **Macro Recorder** — record mouse/keyboard sequences, save and replay (press F9 to stop)
- **File Explorer** — list, read, write, delete files via API
- **Cloudflare Tunnel** — one-click remote access from anywhere
- **Screenshot Cache** — <1s instant screen capture

## Quick Start

```bash
# Clone and go
cd Hermes-CoAgent
python hermes_coagent.py 9123
```

Open **http://localhost:9123/** in any browser.

Or double-click `start.bat` from the folder.

### System Tray App (Recommended)

For a persistent icon by the clock with start/stop/dashboard/emergency controls:

**Double-click `start_tray.bat`** or `start_tray_hidden.vbs`

The tray icon shows:
- 🟢 Green **C** — server running
- 🔴 Red **!** — server error  
- ⚫ Gray **C** — server stopped

Right-click for: Start/Stop Server, Open Dashboard, Emergency Stop/Resume, Settings, Exit.

You can also create a shortcut to `start_tray_hidden.vbs` in your Windows Startup folder (`shell:startup`) so it launches automatically on boot.

## API Endpoints

### Core
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Web dashboard HTML |
| GET | `/ping` | Health check + status |
| GET | `/cursor/pos` | Current mouse position |

### Mouse
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/mouse/move` | `{"x": 500, "y": 400}` |
| POST | `/mouse/click` | `{"button": "left"}` |
| POST | `/mouse/doubleclick` | `{"button": "left"}` |
| POST | `/mouse/drag` | `{"x1":0,"y1":0,"x2":500,"y2":400}` |
| POST | `/mouse/scroll` | `{"clicks": -3}` |

### Keyboard
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/key/type` | `{"text": "hello world"}` |
| POST | `/key/press` | `{"keys": ["ctrl", "c"]}` |

### Screen
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/screen` | Cached screenshot (image) |
| GET | `/screenshot/fresh` | Force fresh screenshot |
| GET | `/screen/base64` | Base64-encoded screenshot |

### Smart
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/chain` | Execute multiple actions: `{"actions": [...]}` |
| POST | `/act` | Execute action + return before/after screenshots |

### Find
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/ocr/find` | `{"text": "Save", "region": [x,y,w,h]}` |
| POST | `/visual/find` | `{"template_path": "C:/img.png", "confidence": 0.8}` |

### Windows
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/windows` | List all open windows |
| POST | `/windows/activate` | `{"title": "Chrome"}` |

### Files
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/file/list` | `{"path": "C:/Users/Admin/Desktop"}` |
| POST | `/file/read` | `{"path": "C:/file.txt"}` |
| POST | `/file/write` | `{"path": "C:/file.txt", "content": "..."}` |
| POST | `/file/delete` | `{"path": "C:/file.txt"}` |

### Macros
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/macro/list` | List saved macros |
| POST | `/macro/record` | `{"name": "open_vscode"}` — press F9 to stop |
| POST | `/macro/run` | `{"name": "open_vscode"}` |
| POST | `/macro/delete` | `{"name": "open_vscode"}` |

### Other
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/clipboard/set` | `{"text": "..."}` |
| GET | `/clipboard/get` | Get clipboard text |
| POST | `/app/open` | `{"path": "notepad.exe"}` |
| POST | `/app/run` | `{"cmd": "dir", "timeout": 30}` |
| GET | `/monitors` | Monitor layout |
| POST | `/tts/speak` | `{"text": "hello"}` |

### Emergency
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/emergency/stop` | Lock all input immediately |
| POST | `/emergency/resume` | Unlock input |
| GET | `/emergency/status` | Current emergency state |
| *(keyboard)* | `Ctrl+Alt+Shift` | Instant emergency stop |

### Tunnel
| Method | Route | Description |
|--------|-------|-------------|
| POST | `/tunnel/start` | Start Cloudflare tunnel |
| POST | `/tunnel/stop` | Stop tunnel |
| GET | `/tunnel/status` | Tunnel status + URL |

### History
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/history` | Last N actions |
| POST | `/replay` | Replay last N actions |

## Installation

**One-liner installer:**
```bash
python install.py
```

**Manual:**
```bash
pip install pyautogui flask pillow pynput mss pygetwindow pyperclip pytesseract opencv-python edge-tts psutil
python hermes_coagent.py 9123
```

## Autostart on Boot

```powershell
# Run once
.\setup_autostart.ps1
```

## Requirements

- Windows 10/11
- Python 3.8+
- Tesseract OCR *(optional — for OCR feature)*
- PySide6 *(for system tray app — optional)*: `pip install PySide6`

## Security

- Localhost-only by default (127.0.0.1:9123)
- Emergency stop via API or keyboard combo
- Tunnel is opt-in (requires manual `POST /tunnel/start`)
- No persistence, no telemetry, no internet without tunnel
