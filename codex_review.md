# Codex Audit: Hermes CoAgent

## Files to Read
- C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py
- C:\Users\Admin\Desktop\Hermes CoAgent\coagent_tray.py

## The Problem
The cursor pulse ring system uses a PowerShell Add-Type / Windows Forms overlay that is NOT visible on screen. It likely runs headless or fails silently (captured in try/except pass with no logging).

## Your Mission

### 1. Diagnose the Cursor Pulse Bug
Read both files fully. Find why _cursor_pulse() rings are not visible on the Windows desktop -- they should draw a colored circle at cursor position that fades out over ~200ms. Currently shows nothing.

### 2. Fix the Root Cause
The PowerShell overlay Form approach is failing. Replace it with one of these working approaches (pick the best one):

**Option A (Recommended):** Create a new helper file `pulse_overlay.py` using **tkinter** that creates a borderless, transparent, topmost window with a colored circle that fades out. Tkinter is part of Python stdlib -- no dependencies needed.
- The overlay Form should accept x, y, color_r, color_g, color_b as command-line args
- Show a 36x36 pixel borderless window centered at (x, y)
- Semi-transparent filled circle (alpha ~100) that fades over ~300ms then auto-closes

**Option B:** Pure Python + win32gui overlay approach (if tkinter has issues)

**Option C:** Fix the existing PowerShell Add-Type approach if the issue is just a missing [System.Windows.Forms] assembly reference

Pick Option A. Create pulse_overlay.py, then update _cursor_pulse() in hermes_coagent.py to call it via subprocess instead of PowerShell.

### 3. Tray Icon Feedback
In coagent_tray.py, add a "flash" method that briefly changes the tray icon color when an action executes. The tray needs to poll or receive a signal when the server runs actions, then flash the icon white for 200ms before returning to green.

Best approach: Add a new endpoint to the server (/status/flash or similar) that the tray polls. Or simpler: add a websocket-less SSE event for "action_executed" that the tray listens on.

### 4. Code Quality Review
Check for:
- Dead code or unused imports
- Error handling gaps (especially in _cursor_pulse and _pulse_before_action)
- Thread safety issues
- Any hardcoded paths that should be configurable
- Console output that should use logging

### 5. Suggest New Features
List 5-10 potential NEW features for Hermes CoAgent that would make it even more powerful. 1-liner each, don't implement them.

### 6. Final Verification
After making changes, run: python hermes_coagent.py 9123 (it will start on port 9123)
Then verify the server starts without errors. Kill it with Ctrl+C after confirming.

## Output
Write your full analysis to C:\Users\Admin\Desktop\Hermes CoAgent\codex_report.md including:
1. What was wrong with the pulse rings
2. What you changed and why
3. All code changes made
4. Feature suggestions list
