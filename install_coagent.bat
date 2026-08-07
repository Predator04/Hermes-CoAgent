@echo off
REM Hermes CoAgent — One-Command Installer (Zero Dependencies)
REM Download and double-click. No git, no Python needed upfront.

setlocal enabledelayedexpansion

echo.
echo ==========================================
echo  Hermes CoAgent v1 — One-Click Installer
echo ==========================================
echo.

set "COAGENT_DIR=%LOCALAPPDATA%\Hermes CoAgent"
set "ZIP=%TEMP%\coagent.zip"

:: Step 1: Download latest code (no git required)
echo [1/5] Downloading CoAgent...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/Predator04/Hermes-CoAgent/archive/refs/heads/main.zip' -OutFile '%ZIP%'" 2>nul
if not exist "%ZIP%" (
    echo   ERROR: Download failed. Check internet connection.
    pause
    exit /b 1
)

:: Remove old install
if exist "%COAGENT_DIR%" rmdir /s /q "%COAGENT_DIR%" 2>nul
mkdir "%COAGENT_DIR%" 2>nul

:: Extract
echo   Extracting...
powershell -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%TEMP%\coagent_extract' -Force" 2>nul
:: Move contents (GitHub wraps in Hermes-CoAgent-main folder)
move "%TEMP%\coagent_extract\Hermes-CoAgent-main\*" "%COAGENT_DIR%\" >nul 2>&1
rmdir /s /q "%TEMP%\coagent_extract" 2>nul
del "%ZIP%" 2>nul
echo   Installed to: %COAGENT_DIR%

:: Step 2: Find or install Python
echo.
echo [2/5] Checking Python...
set PYTHON=
set PYTHONW=

:: Check common install locations first
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Program Files\Python313\python.exe"
) do (
    if exist %%p (
        if "!PYTHON!"=="" set "PYTHON=%%p"
        set "PYTHONW=%%~dppythonw.exe"
    )
)

:: Try PATH
if "%PYTHON%"=="" (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%i in ('where python') do set "PYTHON=%%i"
    )
)

if "%PYTHON%"=="" (
    echo   Python not found. Install from https://www.python.org/downloads/
    echo   Then run this installer again.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
echo   Found: %PYTHON%

:: Step 3: Install dependencies
echo.
echo [3/5] Installing dependencies...
"%PYTHON%" -m pip install --upgrade pip -q 2>nul
"%PYTHON%" -m pip install flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss psutil keyboard mouse pynput playwright py-cpuinfo croniter requests -q 2>&1
echo   Done.

:: Step 4: Create shortcuts
echo.
echo [4/5] Creating shortcuts...

:: Start Menu folder
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Hermes CoAgent"
if not exist "%SM%" mkdir "%SM%"

:: Main shortcut
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SM%\CoAgent.lnk'); $s.TargetPath = 'powershell.exe'; $s.Arguments = '-ExecutionPolicy Bypass -WindowStyle Hidden -File \"%COAGENT_DIR%\launch_all.ps1\"'; $s.WorkingDirectory = '%COAGENT_DIR%'; $s.Save()" 2>nul

:: Auto-start on boot
set "SU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SU%\CoAgent.lnk'); $s.TargetPath = 'powershell.exe'; $s.Arguments = '-ExecutionPolicy Bypass -WindowStyle Hidden -File \"%COAGENT_DIR%\launch_all.ps1\"'; $s.WorkingDirectory = '%COAGENT_DIR%'; $s.Save()" 2>nul

echo   Created Start Menu shortcuts + auto-start

:: Step 5: Launch
echo.
echo [5/5] Starting CoAgent...
start "" /B powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%COAGENT_DIR%\launch_all.ps1"

:: Wait for server
echo   Waiting for server...
timeout /t 5 >nul

:: Done
echo.
echo ==========================================
echo  Hermes CoAgent is installed and running!
echo.
echo  Dashboard: http://127.0.0.1:9123
echo  Tray icon: Purple 'C' in system tray
echo  Installed: %COAGENT_DIR%
echo.
echo  Auto-starts on every reboot.
echo ==========================================
start http://127.0.0.1:9123
timeout /t 3 >nul
