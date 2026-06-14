@echo off
title Hermes CoAgent - Session Repair
cd /d "C:\Users\Admin\Desktop\Hermes CoAgent"
echo =============================================
echo Hermes CoAgent - Desktop Session Repair Tool
echo =============================================
echo.
echo The server is running but can't access your
echo desktop mouse/keyboard because it was
echo launched from a non-interactive session.
echo.
echo This tool will kill it and relaunch it
echo from your interactive desktop session.
echo.
echo Press any key to continue...
pause >nul

echo Killing old server...
taskkill /f /im "pythonw.exe" 2>nul
timeout /t 2 /nobreak >nul

echo.
echo Launching server with interactive desktop access...
start "" /B "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" 9123

timeout /t 3 /nobreak >nul

curl -s http://localhost:9123/ping >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Server is running with desktop access!
) else (
    echo [FAIL] Server did not start.
    pause
    exit /b 1
)

timeout /t 1 /nobreak >nul

:: Test if cursor works
curl -s http://localhost:9123/cursor/pos
echo.

echo.
echo =============================================
echo Session repair complete! Close this window.
echo =============================================
timeout /t 5 /nobreak >nul