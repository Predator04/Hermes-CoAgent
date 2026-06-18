@echo off
REM Hermes CoAgent Launcher v7.0
REM Only kills CoAgent processes, not other Python instances.
cd /d "%~dp0"
title CoAgent Launcher
echo Killing stale CoAgent processes...
for /f "tokens=2" %%a in ('tasklist /fi "WINDOWTITLE eq Hermes*" 2^>nul ^| findstr python') do taskkill /pid %%a /f 2>nul
for /f "tokens=2" %%a in ('tasklist /fi "IMAGENAME eq pythonw.exe" /fi "WINDOWTITLE eq *Tray*" 2^>nul ^| findstr pythonw') do taskkill /pid %%a /f 2>nul
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
start "" "%PYTHON%" "%~dp0hermes_coagent.py" --secure
echo CoAgent v7.0 started - look for purple 'C' in system tray
ping -n 3 127.0.0.1 >nul
