# Hermes CoAgent — Codex: Optimize Tray Menu + Full Settings Overhaul

## File: `C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py`

## Mission

### 1. Fix Right-Click Slowness (CRITICAL)

Right-clicking the tray icon takes 2-5 seconds to show the menu. Fix all of these:

**A) `_build_menu()` rebuilds EVERYTHING from scratch on every right-click** 
- PySide6's `setContextMenu()` re-evaluates the menu lazily — but the code calls `self.menu.clear()` then rebuilds all actions, submenus, and clipboard items.
- **FIX**: Build the static menu ONCE in `__init__()`. Only update dynamic parts (status text, stats, QA items, clipboard items) when they actually change — not on every menu open.
- Solution: Set `contextMenuPolicy = Qt.CustomContextMenu` on the tray icon, or better: use `QMenu`'s `aboutToShow` signal to only refresh dynamic items instead of rebuilding the whole tree. OR the simplest approach: build the full menu once in `__init__`, hold references to dynamic QActions, and only call `.setText()` or `_build_qa_menu()` / `_build_clip_menu()` on timer ticks / status changes.

**B) Clipboard polling on every notification tick (3s) blocks UI**
- The 3-second timer calls `QApplication.clipboard().text()` which is a cross-process COM call on Windows — SLOW.
- **FIX**: Only poll clipboard every 30 seconds instead of every 3. Or use the `QClipboard.changed` signal instead of polling.

**C) `_api()` calls block the UI thread**
- Both `_refresh_stats()` and `_poll_notifications()` call `urllib.request.urlopen()` synchronously on the Qt main thread. If the server is slow or unreachable, it locks the UI.
- **FIX**: Use `QThread` or `QTimer.singleShot(0, lambda: ...)` with a background thread for API calls. Easiest: wrap the API polling in a `threading.Thread` that emits signals back.

**D) Menu has too many separators and nested submenus**
- 10+ permanent items + 2 dynamic submenus (QA, clipboard). On every right-click, all of this is re-evaluated.
- **FIX**: Build menu structure ONCE. Keep references to status_action, stats_action, start_stop_action. Update their text with `.setText()` directly. For QA and clipboard submenus, only rebuild them when config changes or clipboard is updated — NOT on every menu show.

### 2. Full Settings Page (REQUIRED)

The current Settings dialog has 3 tabs (General, Quick Actions, About). Build a **proper** settings page with ALL the following tabs:

**Tab 1: General**
- Port (SpinBox) — already exists
- Auto-start server on launch (CheckBox) — exists
- Show desktop notifications (CheckBox) — exists
- Track clipboard history (CheckBox) — exists
- Start minimized to tray (CheckBox) — exists
- **NEW: Screenshot interval** (SpinBox, 0.5-10 sec, default 1.0)
- **NEW: Action cooldown** (DoubleSpinBox, 0.05-1.0 sec, default 0.12)
- **NEW: Max action history** (SpinBox, 100-10000, default 1000)
- **NEW: Emergency hotkey combo** (QLineEdit, default "Ctrl+Alt+Shift")
- **NEW: Theme** (ComboBox: Dark, Light, System — dark for now)
- Save button (exists) — update to save ALL new fields

**Tab 2: Notifications**
- **Enable notifications** (CheckBox) — exists
- **Notify on all actions** (CheckBox, default true)
- **Notify on errors only** (CheckBox, default false)
- **Notification duration** (SpinBox, 1-10 seconds, default 3)
- **Show clipboard change notifications** (CheckBox, default false)
- **Show server status changes** (CheckBox, default true)
- **Notification position** (ComboBox: Bottom-right, Bottom-left, Top-right, Top-left — default Bottom-right)

**Tab 3: Quick Actions** — EXISTS, keep it. The Add/Remove flow is fine.

**Tab 4: Macros & Recording**
- **Default macro name prefix** (LineEdit, default "macro_")
- **Record mouse moves** (CheckBox, default true)
- **Record clicks only** (CheckBox, default false)
- **Max recording duration** (SpinBox, 10-600 seconds, default 120)
- **Stop recording hotkey** (LineEdit, default "F9")

**Tab 5: Tunnel & Remote**
- **Auto-start tunnel on server start** (CheckBox, default false)
- **Tunnel log lines** (SpinBox, 100-5000, default 2000)
- **Show QR on tunnel start** (CheckBox, default true)
- **Restart tunnel on disconnect** (CheckBox, default false)

**Tab 6: Home Automation / AI**
- **Show keepalive actions in log** (CheckBox, default true)
- **Auto-reconnect to Home Assistant** (CheckBox, default true)
- **Max TTS message length** (SpinBox, 100-5000 chars, default 500)

**Tab 7: About** — EXISTS, keep it. Show version, GitHub link, build date.

**MUST: All settings persist to `tray_config.json`** with the existing atomic-save pattern (write .tmp, then replace).

**MUST: Add new DEFAULT_CONFIG keys** for all the new fields.

### 3. Performance Fixes Summary

| Issue | Fix |
|---|---|
| Right-click menu rebuilds entire tree | Build once, update only dynamic items |
| Clipboard poll every 3s (COM call) | Use QClipboard.changed signal OR poll every 30s |
| API calls on Qt main thread | Move stats/notification polling to background thread |
| Stats timer fires even when menu not open | Only fire stats timer when `_stats_timer.isActive()` during right-click. OR keep it running but make the API call non-blocking |
| Config read on every menu build | Config is already in memory via singleton |

### 4. Verification

After all changes:

```powershell
# Syntax
python -c "import py_compile; py_compile.compile(r'C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py', doraise=True); print('OK')"

# Launch tray, right-click instantly
start /B python coagent_tray.py
timeout /t 3
# Manually verify right-click latency < 500ms on next desktop session

# Close tray
taskkill /f /im python.exe
```

### 5. Git Commit

```powershell
cd "C:\Users\Admin\Desktop\Hermes CoAgent"
git add -A
git commit -m "v3.2 - Full settings overhaul + right-click speed optimization"
git push
```
