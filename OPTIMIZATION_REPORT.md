# Hermes CoAgent Optimization Report

Generated: 2026-06-17

## Summary

v6.2 adds **Co-Pilot Mode** — all desktop actions default to `background: True`, using Win32 `SendInput`/`mouse_event` so the cursor stays under **your control**. No pyautogui cursor steal, no focus hijack. You work alongside CoAgent, not fighting it.

Line counts use direct physical line counts from the working tree.

| File | Lines before | Lines after | Reduction |
| --- | ---: | ---: | ---: |
| auth.py | 56 | 56 | 0 |
| coagent_install.py | 141 | 139 | 2 |
| coagent_tray.py | 1441 | 1442 | -1 |
| computer_use_mcp.py | 555 | 557 | -2 |
| hermes_coagent.py | 2639 | 2596 | 43 |
| test_tray.py | 23 | 25 | -2 |
| tray_icon.py | 332 | 304 | 28 |
| uia_engine.py | 837 | 880 | -43 |
| Total | 6024 | 5999 | 25 |

## Co-Pilot Mode (v6.2)

**What it does:** Every desktop input action defaults to background mode. Instead of `pyautogui.moveTo()` (which steals your cursor), CoAgent uses `SetCursorPos` + `mouse_event`/`SendInput` — your real mouse stays where you put it.

**Actions with background paths:**
- **move** → `uia_engine.send_mouse_move(x, y)` — `SetCursorPos`
- **click** → `uia_engine.send_mouse_click(x, y, button, clicks)` — `SetCursorPos` + `mouse_event`
- **type** → `uia_engine.send_keys(text)` — `SendInput` keystrokes
- **hotkey** → `uia_engine.send_input(keys)` — `SendInput` virtual key codes
- **scroll** → `uia_engine.send_scroll(clicks)` — `mouse_event(MOUSEEVENTF_WHEEL)`
- **drag** → `uia_engine.send_mouse_drag(x1,y1,x2,y2,button)` — 20-step smooth interpolation

**Override per-action:** Pass `"background": false` in any action data to force pyautogui (foreground) mode for specific operations.

**API:** `GET /copilot/mode` returns current mode status.

**Flag:** `HAS_SENDINPUT` is set `True` on Windows. When False (non-Windows), falls back to pyautogui.

## Optimizations

- **`hermes_coagent.py:217`**: Added `_interactive_task_xml()` and replaced four duplicated scheduled-task XML literals. This removes repeated boilerplate while keeping the same task settings, command paths, CLI arguments, and XML encoding.
- **`hermes_coagent.py`**: Replaced the pulse color `if/elif` chain with `PULSE_ACTION_COLORS` dict; removed unused pulse class registration helper.
- **`hermes_coagent.py`**: Reused timestamps, file stats, and decoded file text instead of recomputing them. This reduces repeated filesystem calls and duplicate UTF-8 decoding.
- **`hermes_coagent.py`**: Moved command-danger characters to a constant (`DANGEROUS_CMD_CHARS`), moved `fnmatch` out of the inner search loop, and added missing `pyperclip` import for crop OCR clipboard copy.
- **`computer_use_mcp.py`**: Removed unused imports, made SOM generation lazy-load PIL in fast mode, and fixed unreachable append/draw block after `continue`. Capture mode="som" now actually returns overlay elements.
- **`computer_use_mcp.py`**: Replaced blocking `time.sleep()` calls inside async tools with `asyncio.sleep()`. This avoids blocking the MCP event loop during double-click, chained double-click, and wake-screen operations.
- **`computer_use_mcp.py`**: Restored OCR fallback in fast mode after lazy imports and made empty chains return `actions_completed: 0` instead of depending on an undefined loop variable.
- **`tray_icon.py`**: Made the screenshot cache format-aware so cached PNG bytes are not returned for JPEG requests, and clear both data and cache key on `/cache/clear`.
- **`tray_icon.py`**: Added `_send_body()` helper for repeated HTTP response headers and body writes. Reduced repeated screenshot, health, cache, 404, and UIA response boilerplate.
- **`uia_engine.py`**: Reused one UIA snapshot per SOM bridge/per-window run instead of taking a fresh snapshot for every element/window. This is the largest runtime performance improvement in the UIA path.
- **`uia_engine.py`**: Added compact background mouse/key compatibility helpers: `send_mouse_move`, `send_mouse_click`, `send_mouse_drag`, `send_scroll`, `send_input`, `send_keys`. These are the low-level Win32 input wrappers powering Co-Pilot Mode.
- **`coagent_tray.py`**: Reworked `_api()` to set the HTTP method explicitly and build empty POST bodies without recreating the request object. Removed unused imports.
- **`coagent_install.py`**: Fixed the uninstall command text, removed unused imports, simplified uninstall/remove branch.
- **`test_tray.py`**: Added `ICON_SIZE` to replace repeated icon-size literals in the pystray smoke test.

## Version History

| Version | Date | Description |
| --- | --- | --- |
| v6.0 | 2026-06-17 | Security audit + fix (11 Critical/High findings fixed) |
| v6.1 | 2026-06-17 | Auth default-on, Codex audit all findings fixed |
| **v6.2** | **2026-06-17** | **Co-Pilot Mode + Codex optimization pass** |

## Risks And Follow-Up Tests

- Runtime-test the desktop server path: `python hermes_coagent.py`, then /ping, /screen, /screenshot/jpeg, /uia/tree, /som/screenshot, and one background click/move action.
- Runtime-test the tray relay cache by requesting /screen, /screen?format=jpeg, and /cache/clear rapidly.
- Runtime-test MCP capture(mode="som"), chain([]), double_click, and wake_screen once the MCP dependency/server path is available.
- uia_engine.py grew because compact background input wrappers were needed by the main-server HAS_SENDINPUT path.
