@echo off
title Hermes CoAgent Tray
cd /d "%~dp0"
echo Killing old server processes...
taskkill /f /fi "IMAGENAME eq pythonw.exe" /fi "CMDLINE ne *" 2>nul
:: Filter: only kill pythonw that are running the server, not other pythonw
wmic process where "name='pythonw.exe' and commandline like '%%hermes_coagent%%'" delete >nul 2>&1
timeout /t 2 /nobreak >nul

echo Starting Hermes CoAgent Tray...
echo (Will appear in system tray by the clock)
echo.

:: Use Python 3.13 if available, fallback to PATH
if exist "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" (
    start /min "" "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" "%~dp0coagent_tray.py"
) else (
    start /min "" pythonw "%~dp0coagent_tray.py"
)

:: Close the cmd window so only the tray icon remains
exit
