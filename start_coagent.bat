@echo off
REM Hermes CoAgent Launcher v6.0
REM Requires Python 3.10+ with: flask pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray
cd /d "%~dp0"
title CoAgent Launcher
echo Killing stale CoAgent processes...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
ping -n 4 127.0.0.1 >nul

echo Detecting Python...
REM Try common pythonw locations, fall back to python.exe
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
echo Launching CoAgent with secure auth...
echo To access from other devices, add --allow-external
start "" "%PYTHON%" "%~dp0hermes_coagent.py" --secure
echo CoAgent started - look for purple 'C' in system tray
echo Auth token will be shown in coagent_server.log
ping -n 3 127.0.0.1 >nul
