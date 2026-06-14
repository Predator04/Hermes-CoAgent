@echo off
title Hermes CoAgent Tray
cd /d "%~dp0"
echo Starting Hermes CoAgent Tray...
echo (Will appear in system tray by the clock)
echo.

:: Use Python 3.13 if available, fallback to PATH
if exist "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe" (
    start /min "" "C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe" "%~dp0coagent_tray.py"
) else (
    start /min "" python "%~dp0coagent_tray.py"
)

:: Close the cmd window so only the tray icon remains
exit
