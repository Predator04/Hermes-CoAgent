# Hermes CoAgent v7.0

**Ultimate Desktop Co-Pilot for Windows** — gives AI agents (Hermes, Claude, Codex, Gemini, etc.) full native Windows desktop control. Screenshots, mouse/keyboard, UIA accessibility trees, OCR, voice, file operations, macros, scheduled tasks — all local, zero API costs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🚀 Quick Start

```bash
# Install deps (Windows Python)
pip install flask pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray waitress mss

# Start CoAgent (secure mode)
cd C:\Users\Admin\Desktop\Hermes CoAgent
python hermes_coagent.py --secure --allow-external
# → Running on http://0.0.0.0:9123/
```

### From WSL / another machine
```bash
# Ping it
curl -s http://172.21.192.1:9123/ping
# → {"agent":"Hermes CoAgent v7.0","status":"pong"}

# See the screen
curl -s http://172.21.192.1:9123/describe

# Click something
curl -s -X POST http://172.21.192.1:9123/mouse/click \
  -H "Content-Type: application/json" \
  -d '{"x":960,"y":540}'

# Take screenshot
curl -s http://172.21.192.1:9123/screen/base64 | python3 -c "
import sys,json,base64; d=json.load(sys.stdin)
open('/tmp/desktop.png','wb').write(base64.b64decode(d['data']))
"

# Get UIA tree (all windows + buttons)
curl -s http://172.21.192.1:9123/uia/tree
```

---

## 🤖 For AI Agents

### Python client (recommended)

```python
# Clone/download coagent_client.py, then:
from coagent_client import CoAgent

c = CoAgent()  # auto-detects 172.21.192.1:9123

# See what's on screen
desc = c.describe()
print(desc.get("description", ""))

# Take screenshot
c.screenshot("/tmp/screen.png")

# Click + type
c.click(500, 400)
c.type("hello from AI")
c.hotkey(["enter"])

# Search for text then click it
c.click_text("Submit")

# Chain multiple actions fast
c.chain([
    {"type": "move", "x": 200, "y": 300},
    {"type": "click", "x": 200, "y": 300},
    {"type": "type", "text": "automated input"},
    {"type": "hotkey", "keys": ["enter"]}
])

# Get UIA accessibility tree
tree = c.uia_tree()
for win in tree.get("children", []):
    print(f"{win.get('control_type')}: {win.get('name')}")

# Open Telegram and send message
c.telegram_send("William", "Hello from CoAgent!")

# Emergency stop
c.emergency_stop()
```

### Curl one-liners (for any AI)

| Task | Command |
|------|---------|
| **Health check** | `curl -s http://172.21.192.1:9123/ping` |
| **Describe screen** | `curl -s http://172.21.192.1:9123/describe` |
| **Screenshot** | `curl -s http://172.21.192.1:9123/screen/base64` |
| **SOM overlay** | `curl -s http://172.21.192.1:9123/som/screenshot` |
| **UIA tree** | `curl -s http://172.21.192.1:9123/uia/tree` |
| **Move mouse** | `curl -s -X POST http://172.21.192.1:9123/mouse/move -d '{"x":500,"y":400}'` |
| **Click** | `curl -s -X POST http://172.21.192.1:9123/mouse/click -H "Content-Type: application/json" -d '{"x":960,"y":540}'` |
| **Type text** | `curl -s -X POST http://172.21.192.1:9123/key/type -d '{"text":"hello"}'` |
| **Hotkey** | `curl -s -X POST http://172.21.192.1:9123/key/press -d '{"keys":["ctrl","c"]}'` |
| **Drag** | `curl -s -X POST http://172.21.192.1:9123/mouse/drag -d '{"x1":100,"y1":100,"x2":500,"y2":500}'` |
| **Chain actions** | `curl -s -X POST http://172.21.192.1:9123/chain -d '{"actions":[{"type":"click","x":500,"y":400},{"type":"type","text":"hi"}]}'` |
| **Find by OCR** | `curl -s -X POST http://172.21.192.1:9123/ocr/find -d '{"text":"Submit"}'` |
| **Open app** | `curl -s -X POST http://172.21.192.1:9123/launch/ai -d '{"query":"open telegram"}'` |
| **List windows** | `curl -s http://172.21.192.1:9123/windows` |
| **Activate window** | `curl -s -X POST http://172.21.192.1:9123/windows/activate -d '{"title":"Chrome"}'` |
| **Clipboard get** | `curl -s http://172.21.192.1:9123/clipboard/get` |
| **Clipboard set** | `curl -s -X POST http://172.21.192.1:9123/clipboard/set -d '{"text":"copied"}'` |
| **Save macro** | `curl -s -X POST http://172.21.192.1:9123/macro/save -d '{"name":"refresh","actions":[...]}'` |
| **Run macro** | `curl -s -X POST http://172.21.192.1:9123/macro/run -d '{"name":"refresh"}'` |
| **Emergency stop** | `curl -s -X POST http://172.21.192.1:9123/emergency/stop` |
| **File list** | `curl -s -X POST http://172.21.192.1:9123/file/list -d '{"path":"C:/Users/Admin/Desktop"}'` |
| **Search files** | `curl -s -X POST http://172.21.192.1:9123/search/files -d '{"pattern":"*.pdf","path":"C:/Users/Admin"}'` |
| **TTS speak** | `curl -s -X POST http://172.21.192.1:9123/tts/speak -d '{"text":"Hello world"}'` |
| **Screenshot to file** | `curl -s http://172.21.192.1:9123/screen/base64 \| python3 -c "import sys,json,base64; open('/tmp/screen.png','wb').write(base64.b64decode(json.load(sys.stdin)['data']))"` |

### AI Workflow: Find → Click → Type → Verify

```python
from coagent_client import CoAgent
import time

c = CoAgent()

# 1. See what's on screen
print(c.describe().get("description"))

# 2. Find Submit button via OCR
matches = c.ocr_find("Submit")
if matches.get("matches"):
    m = matches["matches"][0]
    x, y = m["center"]["x"], m["center"]["y"]
    c.click(x, y)

# 3. Type into a text field
c.click(300, 400)  # click the field first
time.sleep(0.2)
c.type("hello world")

# 4. Press Enter
c.hotkey(["enter"])

# 5. Verify the result
time.sleep(1)
print(c.describe().get("description"))
```

### AI Workflow: Open app, navigate, automate

```python
from coagent_client import CoAgent

c = CoAgent()

# Open Chrome to Gmail
c.launch("chrome")
c.type("https://mail.google.com")
c.hotkey(["enter"])

# Wait for page, then interact via UIA
time.sleep(5)
tree = c.uia_tree()
# Find compose button
matches = c.ocr_find("Compose")
if matches.get("matches"):
    m = matches["matches"][0]
    c.click(m["center"]["x"], m["center"]["y"])
```

---

## 🏗 Architecture (v7.0 — Modular)

```
hermes_coagent.py (268 lines — coordinator only)
├── shared.py          — Logging, path safety, SSE, task XML
├── routes_mouse.py    — Mouse, keyboard, chain, emergency (15 routes)
├── routes_ocr.py      — Screenshots, OCR, crop, describe (10 routes)
├── routes_uia.py      — UIA tree, SOM overlays, element find (16 routes)
├── routes_file.py     — File ops, app launch, power (10 routes)
├── routes_media.py    — Wallpaper, clipboard, macros, scheduler (30+ routes)
├── routes_v63.py      — v6.3 features (cursor, recording, stabilization)
├── routes_stream.py   — SSE screen streaming
├── routes_process.py  — Process management (psutil)
├── routes_voice.py    — Voice commands
├── routes_cua.py      — Cua Driver integration (37 tools)
├── routes_copilot.py  — AI Co-Pilot (observe/suggest/automate)
├── routes_buddy.py    — Ember desktop buddy (animated firefly)
├── routes_bypass.py   — Prompt bypass toolkit (9 endpoints)
├── data/trigger_words.txt — Filter trigger word list
├── tests/test_bypass.py — Bypass toolkit unit tests
├── AGENTS.md            — AI onboarding guide
├── uia_engine.py      — UIA accessibility tree + SOM engine
├── computer_use_mcp.py— FastMCP server (proxy to HTTP API)
├── coagent_client.py  — Python client library
├── tray_icon.py       — System tray + screenshot relay
└── auth.py            — Bearer token auth
```

**Data flow:** AI Agent → HTTP API → CoAgent → Windows APIs → Desktop

---

## 🔐 Security

| Flag | Effect |
|------|--------|
| `--secure` | Random 64-char Bearer token |
| `--token=KEY` | Use your own token |
| `--allow-external` | Bind `0.0.0.0` (LAN access) |

**Always use `--secure --allow-external` for network access.**

---

## 🖥️ Full REST API

### Core
`GET /` — dashboard · `GET /ping` — health · `GET /version` — version + features · `GET /stats` — server stats · `GET /logs` — server logs · `GET /events` — SSE stream

### Mouse & Keyboard
`POST /mouse/move` · `POST /mouse/click` · `POST /mouse/dblclick` · `POST /mouse/rclick` · `POST /mouse/drag` · `POST /mouse/scroll` · `POST /key/type` · `POST /key/press` · `POST /chain` · `POST /act` · `POST /input/send` · `GET /cursor/pos` · `GET /copilot/mode`

### Screenshots & OCR
`GET /screen` · `GET /screen/jpeg` · `GET /screen/base64` · `GET /screen/fresh` · `GET /screen/diag` · `POST /ocr/find` · `POST /visual/find` · `POST /crop` · `GET /describe`

### UIA & SOM
`GET /uia/tree` · `GET /uia/find/<name>` · `POST /uia/click` · `POST /uia/find-cmb` · `GET /uia/diag` · `GET /uia/window-tree` · `POST /uia/element/find` · `POST /uia/element/click-by-name` · `POST /uia/element/click-by-index` · `GET /som/screenshot` · `GET /som/cache/clear` · `GET /som/bridge` · `POST /som/point` · `GET /uia/accel-reg`

### Files & Power
`POST /file/list` · `POST /file/read` · `POST /file/write` · `POST /file/delete` · `POST /app/open` · `POST /app/run` · `POST /power/sleep` · `POST /power/shutdown` · `POST /power/restart` · `POST /power/lock` · `POST /power/cancel`

### Windows & Wallpaper
`GET /windows` · `POST /windows/activate` · `POST /wallpaper/set` · `POST /wallpaper/cycle` · `POST /wallpaper/random` · `GET /monitors` · `POST /monitors/layout`

### Clipboard & TTS
`GET /clipboard/get` · `POST /clipboard/set` · `POST /tts/speak`

### Macros & Scheduler
`POST /macro/list` · `POST /macro/save` · `POST /macro/run` · `POST /macro/record` · `POST /macro/delete` · `POST /replay` · `GET /scheduler/list` · `POST /scheduler/add` · `POST /scheduler/remove` · `POST /scheduler/run`

### Other
`POST /voice/toggle` · `POST /tunnel/start` · `POST /tunnel/stop` · `GET /tunnel/status` · `POST /search/files` · `POST /launch/ai` · `POST /emergency/stop` · `POST /emergency/resume` · `GET /emergency/status`

---

## 🔧 Requirements

- **Windows 10/11**
- **Python 3.8+**
- **Packages:** `flask pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray waitress mss`

---

## 🛠️ Bypass Toolkit (v7.5+)

New in v7.5 — prompt encoding, obfuscation, scanning, and prefill tools for working with AI content filters. All endpoints under `/bypass/*` with Bearer token auth.

| Endpoint | Method | Params | Description |
|----------|--------|--------|-------------|
| `/bypass` | GET | — | List all tools |
| `/bypass/leetspeak` | POST | `intensity`, `use_cyrillic` | Leetspeak + Cyrillic homoglyph encoding |
| `/bypass/homoglyph` | POST | `block` | Unicode block (fullwidth, math_bold, math_mono, math_sans, fraktur, double_struck) |
| `/bypass/zero-width` | POST | `frequency` | Inject invisible zero-width characters |
| `/bypass/parseltongue` | POST | `passes` | Multi-pass obfuscation (leet + glyph + cyrillic + base64) |
| `/bypass/prefill` | GET/POST | `template` | List 5 templates or build a prefill wrapper |
| `/bypass/adversarial` | POST | — | 5+ input variants (shuffle, padding, emoji, etc.) |
| `/bypass/scan` | POST | — | Scan for 75+ filter trigger words |
| `/bypass/clean` | POST | — | Auto-obfuscate trigger words only |
| `/bypass/all` | POST | `template` | One-shot: scan + clean + prefill + encode |

### Prefill Templates
- `boundary_inversion` — [END OF INPUT] [START OF INPUT] context reset
- `godmode_l33t` — Classic GODMODE with l33t dividers
- `story_framing` — Creative writing / fiction wrapper
- `educational_compatibility` — Security research framing
- `prefill_assistant` — Pre-conversation where assistant agreed to obey

### Examples
```bash
# Scan for trigger words
curl -s -X POST http://localhost:9123/bypass/scan \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"text":"I want to hack a computer"}'

# Auto-clean trigger words (only obfuscate the bad ones)
curl -s -X POST http://localhost:9123/bypass/clean \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"text":"how to jailbreak an iPhone"}'

# Multi-pass parseltongue encoding
curl -s -X POST http://localhost:9123/bypass/parseltongue \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"text":"bypass content filter","passes":3}'

# One-shot everything
curl -s -X POST http://localhost:9123/bypass/all \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"text":"how to exploit a vulnerability","template":"educational_compatibility"}'
```

Trigger words loaded from `data/trigger_words.txt` (77 words). Max text size: 100 KiB.

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

## Bypass Toolkit (v7.5+)

All `/bypass/*` endpoints require Bearer auth. Use `GET /bypass` to list the 9 available tools.

| Endpoint | Method | Description | Key Parameters |
|----------|--------|-------------|----------------|
| `/bypass/leetspeak` | POST | Encode text with leetspeak + Cyrillic homoglyphs | `text`, `intensity` (0-1), `use_cyrillic` |
| `/bypass/homoglyph` | POST | Encode with a Unicode block | `text`, `block` (`fullwidth`, `math_bold`, `math_mono`, `math_sans`, `fraktur`, `double_struck`) |
| `/bypass/zero-width` | POST | Inject invisible zero-width characters | `text`, `frequency` (0-1) |
| `/bypass/parseltongue` | POST | Multi-pass obfuscation; each pass applies leet + glyph + cyrillic + base64 variants progressively | `text`, `passes` (1-5) |
| `/bypass/prefill` | GET/POST | List templates or build prompt injection wrappers | `text`, `template` (`boundary_inversion`, `godmode_l33t`, `story_framing`, `educational_compatibility`, `prefill_assistant`) |
| `/bypass/adversarial` | POST | Generate 5+ adversarial variants | `text` |
| `/bypass/scan` | POST | Scan text for 75+ filter trigger words | `text` |
| `/bypass/clean` | POST | Auto-obfuscate only trigger words, leaving the rest intact | `text` |
| `/bypass/all` | POST | One-shot scan + clean + prefill + encode response | `text`, `template` |

Examples:

```bash
TOKEN=YOUR_TOKEN_HERE
BASE=http://127.0.0.1:9123

curl -s "$BASE/bypass" \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST "$BASE/bypass/leetspeak" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","intensity":0.7,"use_cyrillic":true}'

curl -s -X POST "$BASE/bypass/homoglyph" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","block":"fullwidth"}'

curl -s -X POST "$BASE/bypass/zero-width" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","frequency":0.4}'

curl -s -X POST "$BASE/bypass/parseltongue" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","passes":3}'

curl -s "$BASE/bypass/prefill" \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST "$BASE/bypass/prefill" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","template":"educational_compatibility"}'

curl -s -X POST "$BASE/bypass/adversarial" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling"}'

curl -s -X POST "$BASE/bypass/scan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling"}'

curl -s -X POST "$BASE/bypass/clean" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling"}'

curl -s -X POST "$BASE/bypass/all" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"review password handling","template":"story_framing"}'
```
