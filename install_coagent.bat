@echo off
REM Hermes CoAgent — One-Command Installer
REM Run this on any fresh Windows machine. Handles everything.

setlocal enabledelayedexpansion

echo.
echo ==========================================
echo  Hermes CoAgent — One-Command Installer
echo ==========================================
echo.

:: Step 1: Find/install Python
echo [1/5] Checking Python...
set PYTHON=
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo   Python not found. Installing via winget...
    winget install Python.Python.3.13 --silent --accept-package-agreements
    if %errorlevel% neq 0 (
        echo   ERROR: Could not install Python. Install manually from https://python.org
        pause
        exit /b 1
    )
    :: Refresh PATH
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python313;%LOCALAPPDATA%\Programs\Python\Python313\Scripts"
)
for /f "tokens=*" %%i in ('where python') do set PYTHON=%%i
echo   Using: %PYTHON%

:: Step 2: Clone or pull repo
echo.
echo [2/5] Getting CoAgent code...
set COAGENT_DIR=%ProgramFiles%\Hermes CoAgent
if exist "%COAGENT_DIR%\.git" (
    echo   Updating existing install...
    cd /d "%COAGENT_DIR%"
    git pull origin main
) else (
    echo   Installing to %COAGENT_DIR%
    if not exist "%COAGENT_DIR%" mkdir "%COAGENT_DIR%"
    :: Remove old dir if not a git repo
    rmdir /s /q "%COAGENT_DIR%" 2>nul
    git clone https://github.com/Predator04/Hermes-CoAgent.git "%COAGENT_DIR%"
    cd /d "%COAGENT_DIR%"
)

:: Step 3: Install dependencies
echo.
echo [3/5] Installing dependencies (this may take a minute)...
"%PYTHON%" -m pip install --upgrade pip -q
"%PYTHON%" -m pip install flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss psutil keyboard mouse pynput playwright py-cpuinfo croniter requests -q
echo   Done.

:: Step 4: Create shortcuts
echo.
echo [4/5] Creating shortcuts and auto-start...

:: Start Menu folder
set STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Hermes CoAgent
if not exist "%STARTMENU%" mkdir "%STARTMENU%"

:: Launch shortcut
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTMENU%\CoAgent.lnk'); $Shortcut.TargetPath = 'powershell.exe'; $Shortcut.Arguments = '-ExecutionPolicy Bypass -WindowStyle Hidden -File ""%COAGENT_DIR%\launch_all.ps1""'; $Shortcut.WorkingDirectory = '%COAGENT_DIR%'; $Shortcut.IconLocation = '%COAGENT_DIR%\coagent_icon.ico'; $Shortcut.Save()"

:: Dashboard shortcut
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTMENU%\CoAgent Dashboard.lnk'); $Shortcut.TargetPath = 'http://127.0.0.1:9123'; $Shortcut.Save()"

:: Auto-start on boot (Startup folder)
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP%\CoAgent.lnk'); $Shortcut.TargetPath = 'powershell.exe'; $Shortcut.Arguments = '-ExecutionPolicy Bypass -WindowStyle Hidden -File ""%COAGENT_DIR%\launch_all.ps1""'; $Shortcut.WorkingDirectory = '%COAGENT_DIR%'; $Shortcut.Save()"

echo   Start Menu shortcuts created
echo   Auto-start on boot: ENABLED

:: Step 5: Launch
echo.
echo [5/5] Starting CoAgent...
powershell -ExecutionPolicy Bypass -File "%COAGENT_DIR%\launch_all.ps1"

:: Done
echo.
echo ==========================================
echo  Hermes CoAgent is installed and running!
echo.
echo  Dashboard: http://127.0.0.1:9123
echo  Tray icon: Look for purple 'C' in system tray
echo  Start Menu: Programs ^> Hermes CoAgent
echo.
echo  Auto-starts on every reboot.
echo ==========================================
echo.
timeout /t 5 >nul
start http://127.0.0.1:9123
