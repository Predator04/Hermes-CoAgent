@echo off
REM Hermes CoAgent Launcher v7.0
REM Only kills CoAgent processes, not other Python instances.
cd /d "%~dp0"
title CoAgent Launcher
echo Killing stale CoAgent processes...
for /f "tokens=2" %%a in ('tasklist /fi "WINDOWTITLE eq Hermes*" 2^>nul ^| findstr python') do taskkill /pid %%a /f 2>nul
for /f "tokens=2" %%a in ('tasklist /fi "IMAGENAME eq pythonw.exe" /fi "WINDOWTITLE eq *Tray*" 2^>nul ^| findstr pythonw') do taskkill /pid %%a /f 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'screenshot_relay.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
ping -n 3 127.0.0.1 >nul

echo Detecting Python...
set PYTHON=
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe"
    "C:\Program Files\Python313\pythonw.exe"
    "C:\Python313\pythonw.exe"
) do if exist %%p set PYTHON=%%p

if not defined PYTHON (
    where pythonw >nul 2>nul
    if errorlevel 1 (
        echo pythonw not found, trying python.exe...
        where python >nul 2>nul
        if errorlevel 1 (
            echo ERROR: Python not found!
            pause
            exit /b 1
        )
        for /f "tokens=*" %%i in ('where python') do set PYTHON=%%i
    ) else (
        for /f "tokens=*" %%i in ('where pythonw') do set PYTHON=%%i
    )
)

echo Using: %PYTHON%
echo Launching CoAgent v7.0 with secure auth...
start "" "%PYTHON%" "%~dp0hermes_coagent.py" --secure --allow-external
echo CoAgent v7.0 started - look for purple 'C' in system tray
ping -n 3 127.0.0.1 >nul
echo Checking screenshot relay...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:9124/health' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>nul
if errorlevel 1 (
    echo Starting screenshot relay fallback...
    start "" "%PYTHON%" "%~dp0screenshot_relay.py"
)
