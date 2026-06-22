# Hermes CoAgent - AGENTS.md (AI Onboarding Guide)

## Project Overview

Hermes CoAgent is a Flask-based Windows desktop automation server. It provides REST endpoints for controlling the Windows desktop programmatically: mouse, keyboard, OCR, UIA, file operations, window management, and more. It runs on port 9123, with auth via Bearer token.

## Getting Started

- Launch: `C:\Program Files\Python312\python.exe hermes_coagent.py --token=TOKEN --allow-external`
- Python path: `C:\Program Files\Python312\python.exe`
- Working directory: `C:\Users\Admin\Desktop\Hermes CoAgent\`
- Token: `YOUR_TOKEN_HERE`
- Health check: `GET http://127.0.0.1:9123/health`
- Version: `GET http://127.0.0.1:9123/version`
- Dashboard: `GET http://127.0.0.1:9123/`

## Architecture

- Main file: `hermes_coagent.py` (auth, CORS, rate limiting, watchdog, route registration)
- Route modules in the same directory:
  - `routes_mouse.py` - mouse/keyboard/chain/emergency
  - `routes_ocr.py` - screenshots/OCR/crop/describe
  - `routes_uia.py` - UIA tree/SOM overlays/element find
  - `routes_file.py` - file ops/app launch/power management
  - `routes_media.py` - wallpaper/windows/clipboard/macros/scheduler/voice/tunnel
  - `routes_v63.py` - v6.3 feature routes (cursor/recording/stabilization)
  - `routes_stream.py` - SSE screen streaming
  - `routes_process.py` - process management (psutil)
  - `routes_voice.py` - voice commands
  - `routes_cua.py` - Cua Driver integration (37 tools)
  - `routes_copilot.py` - AI Co-Pilot (observe/suggest/automate)
  - `routes_buddy.py` - Ember desktop buddy
  - `routes_bypass.py` - prompt bypass toolkit (see below)
- `shared.py` - shared utilities (version, logging, paths)

## Bypass Toolkit (`routes_bypass.py`)

All endpoints: `POST` to `/bypass/*` with JSON body `{"text": "..."}`, auth required.

1. `/bypass/leetspeak` - Encode text with leetspeak + Cyrillic homoglyphs
   Params: `intensity` (0-1), `use_cyrillic` (bool)

2. `/bypass/homoglyph` - Encode with Unicode block
   Params: `block` (`fullwidth`, `math_bold`, `math_mono`, `math_sans`, `fraktur`, `double_struck`)

3. `/bypass/zero-width` - Inject invisible zero-width characters
   Params: `frequency` (0-1)

4. `/bypass/parseltongue` - Multi-pass obfuscation (3-5 passes)
   Params: `passes` (1-5)
   Each pass applies leet + glyph + cyrillic + base64 variants progressively.

5. `/bypass/prefill` - Build prompt injection wrappers
   Params: `template` (`boundary_inversion`, `godmode_l33t`, `story_framing`, `educational_compatibility`, `prefill_assistant`)
   `GET /bypass/prefill` lists available templates.

6. `/bypass/adversarial` - Generate 5+ adversarial variants
   Returns: `word_shuffle`, `padded`, `punctuation_shifted`, `emoji_injected`, `zero_width_dense`

7. `/bypass/scan` - Scan text for 75+ filter trigger words
   Returns: `total_matches`, `matches[]` (`word`, `position`, `context`, `severity`), `clean` bool

8. `/bypass/clean` - Auto-obfuscate only trigger words
   Replaces trigger words with leet/mixed-case variants, leaves rest intact.

9. `/bypass/all` - One-shot: scan + clean + prefill + encode
   Returns everything in one call.

## Coding Standards

- Flask Blueprints with `register_routes(app, state, require_auth)` pattern
- Auth handled by global `before_request` in `hermes_coagent.py`
- Use `_json_payload()` + `_get_text()` helpers for route validation
- Auto-clamp floats/ints with `_clamp_float()` / `_clamp_int()`
- Max text size: 100 KiB per request
- Max passes: 5
- Trigger words in `data/trigger_words.txt`
- Tests in `tests/` using Flask test client

## Deployment

- CoAgent launched via `clean_start_coagent.ps1` (in `C:\Windows\Temp`)
- Uses Python 3.12.9 at `C:\Program Files\Python312\python.exe`
- All deps: `flask`, `waitress`, `mss`, `pywinauto`, `psutil`
