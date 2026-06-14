# Hermes CoAgent — Debug Why Tray Icon Doesn't Appear

## File: `C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py`

## The Problem

When the tray app (`coagent_tray.py`) is launched via VBS or directly from WSL, the `pythonw.exe` process shows up in `Get-Process` but with **SessionId = blank** (Session 0), meaning it's running in the services session — not the user's interactive desktop session (Session 1). Therefore the `QSystemTrayIcon` never appears by the clock.

- When user double-clicks `start_tray.bat` from their **Windows desktop**, it works because the batch file runs in the user's interactive session.
- When launched from WSL or the VBS wrapper, it runs in Session 0 and no icon appears.

## Your Task

Read `coagent_tray.py` and find EVERYTHING that could prevent the tray icon from appearing or functioning correctly. Fix ALL of them.

### Known Issues to Investigate & Fix

1. **Session 0 isolation** — The `QApplication` needs to be aware of the desktop session. Can we force it to use the interactive session? Options:
   - Use `pywin32` to enumerate sessions and launch a subprocess in Session 1
   - OR: detect if we're in Session 0 and show a message (not great)
   - OR: the simplest fix — just ensure the launch method correctly inherits the user session. The `.bat` file works. So maybe update the VBS to launch the `.bat` instead of directly calling pythonw?

2. **`QSystemTrayIcon.isSystemTrayAvailable()`** — Call this after creating the tray. If it returns False, show a message box or log why.

3. **`QApplication.setQuitOnLastWindowClosed(False)`** — Already set at line 313. But verify it's actually being called before `self.tray.show()`.

4. **Missing `app.setApplicationName("Hermes CoAgent")`** — Already set. But some Windows tray implementations need `app.setOrganizationName("Edge Foundry")` too.

5. **Icon not setting correctly** — The `_update_icon()` method draws a colored circle programmatically. But `QSystemTrayIcon.setIcon()` requires a valid `QIcon` with a non-null `QPixmap`. Check if the 32x32 pixmap is actually being rendered. Add a fallback to use a built-in system icon (`QIcon.fromTheme`) or a stock icon.

6. **`QMenu` never gets shown because `aboutToShow` is miswired** — Line 557: `self.menu.aboutToShow.connect(self._refresh_menu_dynamic)`. But `_refresh_menu_dynamic` calls `self._refresh_stats()` which calls `self._api_async()`. If the server isn't running yet (first launch, autostart takes 1 second), this might cause an error that silently breaks the menu. Wrap in try/except.

7. **Clipboard signal in __init__** — Line 553: `self._clipboard.dataChanged.connect(self._on_clipboard_changed)` — this connects to the clipboard `dataChanged` signal ONCE in `__init__`. On Windows, this signal fires when the application gains focus. If it fires before the menu is built, it calls `self._build_clip_menu()` which references `self._clip_menu` — ensure `self._clip_menu` is initialized before the clipboard signal connects.

8. **Timers starting before tray.show()** — Lines 561-570: `_stats_timer` and `_notif_timer` start BEFORE `self.tray.show()` (line 572). The timers fire API calls which might hang or slow down the startup. Reorder so timers start AFTER `self.tray.show()`.

9. **`sys.exit(self.app.exec())` needs to be the last thing** — Line 872: `sys.exit(self.app.exec())`. If anything raises an exception before this line, the whole app crashes silently (no console since pythonw.exe). Add a top-level try/except in `if __name__ == "__main__"` that writes to a log file on crash.

10. **Missing `app.setStyle("Fusion")`** — On Windows, PySide6 might pick a style that doesn't support system tray icons properly. Set `app.setStyle("Fusion")` after creating the QApplication.

11. **The `QApplication` might not have a display** — On Windows, `QApplication(sys.argv)` needs a valid display. Since pythonw.exe has no console, ensure the app is properly initialized as a GUI application. Check if `QApplication.instance()` returns None.

12. **Session ID detection** — Add session detection at startup. If SessionId != 1, log a warning and try to re-launch in the user's session using `ps` / `subprocess` with session escalation.

## What to Fix

Fix EVERY issue above. Then:

1. Add a startup log file at `COAGENT_DIR / "tray_debug.log"` that logs every initialization step with timestamps so we can see where it fails.
2. Add robust error handling — any exception in `__init__` should be caught and written to the debug log.
3. Add `QSystemTrayIcon.isSystemTrayAvailable()` check after creation. If False, write to log.
4. Add Session ID detection at the very start. If SessionId == 0 (or blank), write "WARNING: Running in session 0 — tray icon will not appear!" to the debug log.
5. Ensure ALL QActions are created with a parent (the QMenu) so they get cleaned up properly.
6. Test that the tray icon shows by checking `QSystemTrayIcon.supportsMessages()`.

## Verification

```powershell
# Syntax check
python -c "import py_compile; py_compile.compile(r'C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py', doraise=True); print('OK')"

# Lint
python -m py_compile "C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py"
```

## Git Commit

DO NOT commit or push. Just read, fix, and report what you changed. The user will test manually.
