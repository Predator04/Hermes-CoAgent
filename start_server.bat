@echo off
title Hermes CoAgent Server
cd /d "C:\Users\Admin\Desktop\Hermes CoAgent"
echo Hermes CoAgent Server Launcher
echo ===============================
echo.
echo Starting server on port 9123...
echo.

:: Launch pythonw.exe silently (no window)
start "" /B "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" 9123

:: Wait for it
timeout /t 3 /nobreak >nul

:: Check
curl -s http://localhost:9123/ping >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Server is running!
    echo.
    echo Now you can:
    echo   - Open http://localhost:9123/ in your browser
    echo   - Double-click start_tray_hidden.vbs for the tray app
    echo.
) else (
    echo [WARN] Server may not be running. Check Task Manager for pythonw.exe
    echo.
)

echo Close this window or minimize it (server stays running).
echo.
pause