@echo off
title Hermes CoAgent v3
cd /d "%~dp0"
echo ========================================
echo   Hermes CoAgent v3
echo   Ultimate Desktop Co-Pilot
echo ========================================
echo.
echo  Starting CoAgent server...
echo  Dashboard will open in your browser.
echo.
start http://localhost:9123

:: Try multiple Python locations
if exist "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe" (
    "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe" hermes_coagent.py 9123
) else (
    python hermes_coagent.py 9123
)
pause
