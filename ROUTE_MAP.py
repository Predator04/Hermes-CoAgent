# ════════════════════════════════════════════════════════════════
# HERMES COAGENT v7.3 — PERFORMANCE OPTIMIZATIONS
# ════════════════════════════════════════════════════════════════
"""
Hermes CoAgent — Windows Desktop Co-Pilot (Flask REST + MCP server)
====================================================================
Primary entry point for the CoAgent desktop automation system.

ARCHITECTURE:
  hermes_coagent.py  — Main Flask server: REST API + MCP mode + dashboards
  uia_engine.py      — UIA accessibility tree + SOM overlays + background SendInput
  computer_use_mcp.py — FastMCP server proxying to CoAgent (stdin/stdout or SSE)
  auth.py            — Bearer token authentication with secrets.compare_digest

DEPLOYMENT:
  python hermes_coagent.py                    # REST server on :9123
  python hermes_coagent.py --mcp              # MCP stdio mode
  python hermes_coagent.py --secure           # Auth enabled (random token)
  python hermes_coagent.py --token=KEY        # Auth with fixed token
  python hermes_coagent.py --allow-external   # Bind 0.0.0.0 (requires --secure, --token, or env token)

ROUTE MAP (REST API):
  ┌─────────────────────┬──────────────────────────────────────────────────┐
  │ Route               │ Auth  │ Description                              │
  ├─────────────────────┼──────────────────────────────────────────────────┤
  │ GET  /              │ No    │ Web dashboard (DASHBOARD_HTML)            │
  │ GET  /dashboard2    │ No    │ SOM-focused dashboard 2                  │
  │ GET  /ping          │ No    │ Health check + status                    │
  │ GET  /version       │ No    │ Version info + feature list              │
  │ GET  /stats         │ No    │ Server stats (action count, uptime, RAM) │
  │ GET  /logs          │ No    │ Action log buffer                        │
  │ GET  /events        │ No    │ SSE stream for real-time events          │
  │ GET  /history       │ No    │ Action history (limit=N)                 │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /mouse/move    │ Yes   │ Move mouse to X,Y                       │
  │ POST /mouse/click   │ Yes   │ Click (button, x, y)                    │
  │ POST /mouse/dblclick│ Yes   │ Double-click                             │
  │ POST /mouse/rclick  │ Yes   │ Right-click                             │
  │ POST /mouse/drag    │ Yes   │ Drag x1,y1 -> x2,y2                     │
  │ POST /mouse/scroll  │ Yes   │ Scroll wheel (clicks=N)                 │
  │ POST /key/type      │ Yes   │ Type text                                │
  │ POST /key/press     │ Yes   │ Hotkey combo (['ctrl','c'])             │
  │ POST /chain         │ Yes   │ Batch multiple actions                   │
  │ POST /act           │ Yes   │ Action + before/after screenshots        │
  │ POST /minimize      │ Yes   │ Minimize all windows (Session 1)         │
  │ POST /click/session1│ Yes   │ Click at XY on Session 1 (schtasks)     │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ GET  /screen        │ No    │ Cached JPEG screenshot                   │
  │ GET  /screen/jpeg   │ No    │ JPEG screenshot                          │
  │ GET  /screen/base64 │ No    │ Base64 PNG screenshot                    │
  │ GET  /screen/fresh  │ No    │ Fresh JPEG screenshot (force capture)    │
  │ GET  /screen/diag   │ No    │ Session diagnostics                      │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /emergency/stop│ No    │ Emergency stop all input                 │
  │ POST /emergency/resm│ No    │ Resume input                             │
  │ POST /emergency/rstr│ Yes   │ Restart CoAgent server                   │
  │ GET  /emergency/stat│ No    │ Emergency status                         │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /file/list     │ Yes   │ List directory (sanitized)               │
  │ POST /file/read     │ Yes   │ Read file (sanitized, max 50MB)          │
  │ POST /file/write    │ Yes   │ Write file (sanitized)                   │
  │ POST /file/delete   │ Yes   │ Delete file (sanitized)                  │
  │ POST /app/open      │ Yes   │ Launch app (.exe/.lnk/http)              │
  │ POST /app/run       │ Yes   │ Run shell command (sanitized)            │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ GET  /cursor/pos    │ No    │ Current cursor position                  │
  │ GET  /copilot/mode  │ No    │ Background vs foreground input mode      │
  │ GET  /windows       │ No    │ List open windows                        │
  │ POST /windows/activ │ No    │ Activate window by title                 │
  │ GET  /monitors      │ Yes   │ Monitor layout                           │
  │ GET  /monitors/layot│ No    │ Tile visible windows                     │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /ocr/find      │ Yes   │ Find text on screen via OCR              │
  │ POST /visual/find   │ Yes   │ Find image template on screen            │
  │ POST /crop          │ No    │ OCR region -> clipboard                  │
  │ GET  /describe      │ No    │ OCR entire screen to text                │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ GET  /uia/tree      │ No    │ UIA accessibility tree                   │
  │ GET  /uia/snapshot  │ No    │ (alias for /uia/tree)                    │
  │ GET  /uia/find/<nm> │ No    │ Deep search UIA elements by name         │
  │ POST /uia/click     │ Yes   │ Click UIA element by index/name          │
  │ POST /uia/find-cmb  │ No    │ UIA + OCR combined find                  │
  │ GET  /uia/diag      │ No    │ UIA availability diagnostics             │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ GET  /som/screenshot│ No    │ SOM overlay (numbered elements)          │
  │ GET  /som/image     │ No    │ SOM overlay as raw PNG                   │
  │ GET  /som/cache/clr │ No    │ Clear SOM diff cache                     │
  │ GET  /som/bridge    │ No    │ v5.1 SOM with UIA cross-ref              │
  │ GET  /som/per-window│ No    │ Per-window SOM snapshots                 │
  │ POST /som/point     │ No    │ Find UIA element at pixel XY             │
  │ GET  /uia/accel-reg │ No    │ Accelerated region tracking info         │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /input/send    │ Yes   │ Send background keystrokes               │
  │ GET  /clipboard/get │ No    │ Get clipboard text                       │
  │ POST /clipboard/set │ No    │ Set clipboard text                       │
  │ POST /tts/speak     │ Yes   │ Text-to-speech via SAPI                  │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /macro/list    │ No    │ List saved macros                        │
  │ POST /macro/save    │ No    │ Save macro                               │
  │ POST /macro/run     │ No    │ Run macro                                │
  │ POST /macro/record  │ No    │ Start recording macro                    │
  │ POST /macro/delete  │ Yes   │ Delete macro                             │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /tunnel/start  │ Yes   │ Start Cloudflare tunnel                  │
  │ POST /tunnel/stop   │ Yes   │ Stop tunnel                              │
  │ GET  /tunnel/status │ No    │ Tunnel status                            │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /power/sleep   │ No    │ Sleep PC                                 │
  │ POST /power/shutdown│ No    │ Shutdown PC                              │
  │ POST /power/restart │ No    │ Restart PC                               │
  │ POST /power/lock    │ No    │ Lock workstation                         │
  │ POST /power/cancel  │ No    │ Cancel pending shutdown                  │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /wallpaper/set │ No    │ Set wallpaper from path                  │
  │ POST /wallpaper/cycl│ No    │ Cycle wallpaper in folder                │
  │ POST /wallpaper/rndm│ No    │ Random wallpaper from folder             │
  │─────────────────────┼──────────────────────────────────────────────────┤
  │ POST /search/files  │ No    │ Search files by glob                     │
  │ POST /scheduler/add │ No    │ Add scheduled action                     │
  │ GET  /scheduler/list│ No    │ List scheduled actions                   │
  │ POST /scheduler/remv│ No    │ Remove scheduled action                  │
  │ POST /scheduler/run │ No    │ Run scheduled action immediately         │
  │ POST /replay        │ No    │ Replay last N actions                    │
  │ POST /voice/toggle  │ No    │ Voice control toggle                     │
  │ POST /launch/ai     │ No    │ AI smart app launcher                    │
  └─────────────────────┴──────────────────────────────────────────────────┘

SECURITY:
  - Authentication via Bearer token (--secure, --token=KEY, or HERMES_COAGENT_TOKEN)
  - In secure/token mode every route requires Authorization except /, /dashboard2, /ping, /version, /health, /favicon.ico
  - Path traversal protection: _sanitize_path() restricts to USERPROFILE/TEMP/CoAgent
  - Command injection protection: _sanitize_cmd() blocks shell metacharacters
  - No shell=True anywhere — all subprocess calls use argument lists
  - Mutating desktop-control routes are also marked @require_auth for route-level defense
"""
