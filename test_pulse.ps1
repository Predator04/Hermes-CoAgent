$python = "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"

$testCode = @'
"""Standalone tkinter pulse test - fixed position"""
import sys, os, time

os.environ["PYAUTOGUI_FAILSAFE"] = "false"
import pyautogui
pyautogui.FAILSAFE = False

# Get actual screen center
import tkinter as tk
root_check = tk.Tk()
sw = root_check.winfo_screenwidth()
sh = root_check.winfo_screenheight()
root_check.destroy()

print(f"Screen: {sw}x{sh}")

# Try to get cursor, force center if it fails
try:
    x, y = pyautogui.position()
    if x == 0 and y == 0:
        x, y = sw//2, sh//2
except:
    x, y = sw//2, sh//2

print(f"Pulse at: {x},{y}")

# Create window
root = tk.Tk()
root.overrideredirect(True)
root.wm_attributes("-topmost", True)
root.wm_attributes("-transparentcolor", "black")
root.configure(bg="black")

size = 44
root.geometry(f"{size}x{size}+{x-22}+{y-22}")

canvas = tk.Canvas(root, width=size, height=size, bg="black", highlightthickness=0)
canvas.pack()

canvas.create_oval(2, 2, 42, 42, fill="#00FF00", outline="white", width=2)
root.update()
print("Window shown at", x, y)

# Keep visible for 3 seconds
import time
time.sleep(3.0)

for alpha in range(200, 0, -33):
    root.wm_attributes("-alpha", max(0.01, alpha/255))
    root.update()
    time.sleep(0.05)

root.destroy()
print("Done!")
'@

$tempFile = [System.IO.Path]::GetTempFileName() + ".py"
Set-Content -Path $tempFile -Value $testCode -Encoding UTF8

Write-Host "Running tkinter pulse test at screen center..."
Write-Host "LOOK AT CENTER OF YOUR SCREEN for a GREEN CIRCLE!"
& $python $tempFile

Remove-Item $tempFile -Force
