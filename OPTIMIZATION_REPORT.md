# Hermes CoAgent Optimization Report

Generated: 2026-06-17

## Summary

Line counts use direct physical line counts from the working tree. `hermes_coagent.py` was already dirty at the start of this pass, so its "before" count is the pre-edit working-tree count read before optimization.

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

## Optimizations

- `hermes_coagent.py:217`: Added `_interactive_task_xml()` and replaced four duplicated scheduled-task XML literals at `hermes_coagent.py:439`, `hermes_coagent.py:499`, `hermes_coagent.py:1423`, and `hermes_coagent.py:2357`. This removes repeated boilerplate while keeping the same task settings, command paths, CLI arguments, and XML encoding.
- `hermes_coagent.py:102` and `hermes_coagent.py:298`: Replaced the pulse color `if/elif` chain with `PULSE_ACTION_COLORS`; removed the unused pulse class registration helper. This keeps the same colors and direct pulse behavior with less branch code.
- `hermes_coagent.py:762`, `hermes_coagent.py:837`, and `hermes_coagent.py:855`: Reused timestamps, file stats, and decoded file text instead of recomputing them. This reduces repeated filesystem calls and duplicate UTF-8 decoding.
- `hermes_coagent.py:939`, `hermes_coagent.py:2044`, and `hermes_coagent.py:2076`: Moved command-danger characters to a constant, moved `fnmatch` out of the inner search loop, and added the missing local `pyperclip` import for crop OCR clipboard copy.
- `computer_use_mcp.py:31`, `computer_use_mcp.py:200`, and `computer_use_mcp.py:217`: Removed unused imports, made SOM generation lazy-load PIL in fast mode, and fixed an unreachable append/draw block after `continue`. This makes `capture(mode="som")` actually return overlay elements.
- `computer_use_mcp.py:277`, `computer_use_mcp.py:448`, and `computer_use_mcp.py:508`: Replaced blocking `time.sleep()` calls inside async tools with `asyncio.sleep()`. This avoids blocking the MCP event loop during double-click, chained double-click, and wake-screen operations.
- `computer_use_mcp.py:397` and `computer_use_mcp.py:468`: Restored OCR fallback in fast mode after lazy imports and made empty chains return `actions_completed: 0` instead of depending on an undefined loop variable.
- `tray_icon.py:20`, `tray_icon.py:75`, and `tray_icon.py:142`: Made the screenshot cache format-aware so cached PNG bytes are not returned for JPEG requests, and clear both data and cache key on `/cache/clear`.
- `tray_icon.py:109`: Added one `_send_body()` helper for repeated HTTP response headers and body writes. This reduced repeated screenshot, health, cache, 404, and UIA response boilerplate.
- `uia_engine.py:453` and `uia_engine.py:581`: Reused one UIA snapshot per SOM bridge/per-window run instead of taking a fresh snapshot for every element/window. This is the largest runtime performance improvement in the UIA path.
- `uia_engine.py:793` and `uia_engine.py:841`: Added compact background mouse/key compatibility helpers required by the existing `HAS_SENDINPUT` path in `hermes_coagent.py`. This increased `uia_engine.py` line count, but prevents the main server from calling missing functions during background input.
- `coagent_tray.py:410`: Reworked `_api()` to set the HTTP method explicitly and build empty POST bodies without recreating the request object. Removed an unused Qt import and an unused local process variable.
- `coagent_install.py:5` and `coagent_install.py:130`: Fixed the uninstall command text, removed an unused import and unused command string, and simplified the uninstall/remove branch.
- `test_tray.py:6`: Added `ICON_SIZE` to replace repeated icon-size literals in the pystray smoke test.
- `auth.py`: Reviewed but left unchanged to honor the prompt rule not to change auth module logic.

## Verification

- Passed syntax compilation for all Python files with:
  `python - <<compile all *.py with compile(source, filename, "exec")>>`
- Attempted `python computer_use_mcp.py --test`; the sandbox runner timed out after 15000 ms with `windows sandbox: timed out after 15000ms connecting runner pipe-in`.
- Checked for leftover `computer_use_mcp.py --test` Python processes afterward; none were running.

## Risks And Follow-Up Tests

- Runtime-test the desktop server path: `python hermes_coagent.py`, then `/ping`, `/screen`, `/screenshot/jpeg`, `/uia/tree`, `/som/screenshot`, and one background click/move action.
- Runtime-test the tray relay cache by requesting `/screen`, `/screen?format=jpeg`, and `/cache/clear` rapidly.
- Runtime-test MCP `capture(mode="som")`, `chain([])`, `double_click`, and `wake_screen` once the MCP dependency/server path is available.
- `uia_engine.py` grew because compact background input wrappers were needed by the existing main-server `HAS_SENDINPUT` path. If that path is later removed or made foreground-only, those wrappers can be deleted.
