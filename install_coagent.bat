@echo off
REM Hermes CoAgent - One-Command Installer
REM Download and double-click. Tries git, gh, then direct ZIP download.
REM Handles fresh installs, updates in place, and wipe-and-restart.

setlocal enabledelayedexpansion

echo.
echo ==========================================
echo  Hermes CoAgent - One-Click Installer
echo ==========================================
echo.

set "COAGENT_DIR=%LOCALAPPDATA%\Hermes CoAgent"
set "REPO=https://github.com/Predator04/Hermes-CoAgent.git"

:: ---------------------------------------------------------------
:: If an existing install is detected, ask what to do.
:: ---------------------------------------------------------------
if exist "%COAGENT_DIR%\hermes_coagent.py" (
    echo  An existing CoAgent installation was found at:
    echo    %COAGENT_DIR%
    echo.
    echo  What would you like to do?
    echo    [U] Update in place  - keep your token, config, and recordings
    echo    [W] Wipe and reinstall - delete the folder and start fresh
    echo    [C] Cancel
    echo.
    set /p CHOICE="  Choice (U/W/C): "
    if /i "!CHOICE!"=="C" (
        echo  Cancelled.
        exit /b 0
    )
    if /i "!CHOICE!"=="W" (
        echo  Wiping %COAGENT_DIR% ...
        rmdir /s /q "%COAGENT_DIR%" 2>nul
        if exist "%COAGENT_DIR%" (
            echo  WARNING: Could not fully delete the folder. Close CoAgent first, then re-run.
            echo  (taskkill /f /im pythonw.exe  will stop it)
            pause
            exit /b 1
        )
        goto :fresh_download
    )
    if /i "!CHOICE!"=="U" goto :update_in_place
    :: Anything else - treat as update (safe default)
    goto :update_in_place
)

goto :fresh_download

:: ---------------------------------------------------------------
:: UPDATE IN PLACE - download fresh code, overlay onto existing
:: install, preserving .token / config / recordings.
:: ---------------------------------------------------------------
:update_in_place
echo.
echo  Updating in place (keeping your token and settings)...

set "TOKEN="
where gh >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%t in ('gh auth token 2^>nul') do set "TOKEN=%%t"
)

set "STAGE=%TEMP%\coagent_update_stage"
if exist "%STAGE%" rmdir /s /q "%STAGE%" 2>nul
mkdir "%STAGE%"

if not "%TOKEN%"=="" (
    echo   Downloading latest code with auth...
    powershell -NoProfile -Command "$headers = @{'Authorization'='Bearer %TOKEN%'; 'Accept'='application/vnd.github+json'}; Invoke-WebRequest -Uri 'https://api.github.com/repos/Predator04/Hermes-CoAgent/zipball/main' -Headers $headers -OutFile '%STAGE%\coagent.zip'" 2>nul
    if exist "%STAGE%\coagent.zip" (
        powershell -NoProfile -Command "Expand-Archive -Path '%STAGE%\coagent.zip' -DestinationPath '%STAGE%' -Force" 2>nul
        del "%STAGE%\coagent.zip" 2>nul
    )
)

:: Fallback: try git pull if the folder is a git checkout
if not exist "%STAGE%\Predator04-Hermes-CoAgent-*" (
    if exist "%COAGENT_DIR%\.git" (
        echo   Git checkout detected, pulling latest...
        cd /d "%COAGENT_DIR%"
        git pull 2>&1
        goto :got_code
    )
)

:: Overlay the downloaded code onto the existing install.
:: .token / config / recordings are not in the repo, so they survive.
for /d %%d in ("%STAGE%\Predator04-Hermes-CoAgent-*") do (
    echo   Overlaying fresh code...
    robocopy "%%d" "%COAGENT_DIR%" /E /IS /NFL /NDL /NJH /NJS >nul
    if exist "%COAGENT_DIR%\hermes_coagent.py" (
        rmdir /s /q "%STAGE%" 2>nul
        goto :got_code
    )
)

rmdir /s /q "%STAGE%" 2>nul
echo   Update download failed. Falling back to fresh install...
goto :fresh_download

:: ---------------------------------------------------------------
:: FRESH DOWNLOAD - standard 3-method download into an empty dir.
:: ---------------------------------------------------------------
:fresh_download
echo [1/4] Getting CoAgent code...

:: Try method 1: git clone (works if gh CLI is authenticated)
where git >nul 2>nul
if %errorlevel% equ 0 (
    echo   Using git clone...
    if exist "%COAGENT_DIR%" rmdir /s /q "%COAGENT_DIR%" 2>nul
    git clone "%REPO%" "%COAGENT_DIR%" 2>&1
    if exist "%COAGENT_DIR%\hermes_coagent.py" goto :got_code
    echo   git clone failed (may need: gh auth login)
)

:: Try method 2: gh CLI download
where gh >nul 2>nul
if %errorlevel% equ 0 (
    echo   Using gh release download...
    if exist "%COAGENT_DIR%" rmdir /s /q "%COAGENT_DIR%" 2>nul
    mkdir "%COAGENT_DIR%"
    cd /d "%COAGENT_DIR%"
    gh release download --repo Predator04/Hermes-CoAgent --pattern "*.zip" --dir "%COAGENT_DIR%" 2>&1
    :: Extract the zip
    for %%f in ("%COAGENT_DIR%\*.zip") do (
        echo   Extracting %%f...
        powershell -NoProfile -Command "Expand-Archive -Path '%%f' -DestinationPath '%COAGENT_DIR%' -Force" 2>nul
        del "%%f" 2>nul
    )
    if exist "%COAGENT_DIR%\hermes_coagent.py" goto :got_code
    :: GitHub wraps in a subfolder from zip
    for /d %%d in ("%COAGENT_DIR%\Hermes-CoAgent-*") do (
        move "%%d\*" "%COAGENT_DIR%\" >nul 2>&1
        rmdir /s /q "%%d" 2>nul
    )
    if exist "%COAGENT_DIR%\hermes_coagent.py" goto :got_code
)

:: Try method 3: Download ZIP via PowerShell with token from gh
echo   Trying direct download...
if exist "%COAGENT_DIR%" rmdir /s /q "%COAGENT_DIR%" 2>nul
mkdir "%COAGENT_DIR%"

:: Get a token from gh CLI if available
set "TOKEN="
where gh >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%t in ('gh auth token 2^>nul') do set "TOKEN=%%t"
)

if not "%TOKEN%"=="" (
    echo   Downloading with auth...
    powershell -NoProfile -Command "$headers = @{'Authorization'='Bearer %TOKEN%'; 'Accept'='application/vnd.github+json'}; Invoke-WebRequest -Uri 'https://api.github.com/repos/Predator04/Hermes-CoAgent/zipball/main' -Headers $headers -OutFile '%TEMP%\coagent.zip'" 2>nul
    if exist "%TEMP%\coagent.zip" (
        powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\coagent.zip' -DestinationPath '%COAGENT_DIR%' -Force" 2>nul
        del "%TEMP%\coagent.zip" 2>nul
        :: Move from subfolder
        for /d %%d in ("%COAGENT_DIR%\Predator04-Hermes-CoAgent-*") do (
            move "%%d\*" "%COAGENT_DIR%\" >nul 2>&1
            rmdir /s /q "%%d" 2>nul
        )
    )
)

if exist "%COAGENT_DIR%\hermes_coagent.py" goto :got_code

:: All methods failed
echo.
echo   ERROR: Could not download CoAgent.
echo.
echo   Manual install:
echo   1. Download ZIP from: https://github.com/Predator04/Hermes-CoAgent
echo   2. Extract to: %COAGENT_DIR%
echo   3. Run this installer again
echo.
echo   Or install gh CLI: winget install GitHub.cli
echo   Then run: gh auth login
pause
exit /b 1

:got_code
echo   Installed to: %COAGENT_DIR%

:: Step 2: Find or install Python
echo.
echo [2/4] Checking Python...
set PYTHON=

for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "C:\Python313\python.exe"
    "C:\Program Files\Python313\python.exe"
) do (
    if exist %%p if "!PYTHON!"=="" set "PYTHON=%%p"
)

if "%PYTHON%"=="" where python >nul 2>nul && for /f "tokens=*" %%i in ('where python') do set "PYTHON=%%i"

if "%PYTHON%"=="" (
    echo   Python not found.
    start https://www.python.org/downloads/
    echo   Install Python, then run this installer again.
    pause
    exit /b 1
)
echo   Found: %PYTHON%

:: Step 3: Install dependencies
echo.
echo [3/4] Installing dependencies...
"%PYTHON%" -m pip install --upgrade pip -q 2>nul
"%PYTHON%" -m pip install flask waitress pillow pyautogui pywinauto pytesseract pygetwindow pyperclip pystray mss psutil keyboard mouse pynput playwright py-cpuinfo croniter requests -q 2>&1
echo   Done.

:: Step 4: Install + launch
echo.
echo [4/4] Running installer...
cd /d "%COAGENT_DIR%"
"%PYTHON%" install_coagent.py --auto --install-dir "%COAGENT_DIR%"

:: Launch
start "" /B powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%COAGENT_DIR%\launch_all.ps1"

echo.
echo ==========================================
echo  Done! Dashboard: http://127.0.0.1:9123
echo  Tray icon: Purple 'C' in system tray
echo  Auto-starts on every reboot.
echo ==========================================
timeout /t 3 >nul
start http://127.0.0.1:9123
