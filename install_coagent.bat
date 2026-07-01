@echo off
title CoAgent Installer
cd /d "%~dp0"
echo ==========================================
echo   CoAgent Installer & Updater
echo ==========================================
echo.

if "%1"=="--update" goto update
if "%1"=="--uninstall" goto uninstall
if "%1"=="--status" goto status
if "%1"=="--help" goto help

:install
echo This will install Hermes CoAgent to your computer.
echo.
echo What would you like to do?
echo.
echo  [1] Install CoAgent (fresh install)
echo  [2] Update CoAgent (download latest)
echo  [3] Check status
echo  [4] Uninstall
echo  [5] Exit
echo.
set /p choice="Choose (1-5): "

if "%choice%"=="1" goto do_install
if "%choice%"=="2" goto do_update
if "%choice%"=="3" goto do_status
if "%choice%"=="4" goto do_uninstall
if "%choice%"=="5" exit /b
echo Invalid choice
goto install

:do_install
echo.
echo Installing CoAgent...
python install_coagent.py --auto
if %errorlevel% neq 0 (
    echo.
    echo Python not found. Attempting to find Python...
    where python3 2>nul
    if %errorlevel% equ 0 (
        python3 install_coagent.py --auto
    ) else (
        echo Error: Python not found in PATH.
        echo Please install Python 3.10+ from python.org
    )
)
echo.
pause
exit /b

:do_update
python install_coagent.py --update
if %errorlevel% neq 0 python3 install_coagent.py --update
echo.
pause
exit /b

:do_status
python install_coagent.py --status
if %errorlevel% neq 0 python3 install_coagent.py --status
echo.
pause
exit /b

:do_uninstall
python install_coagent.py --uninstall
if %errorlevel% neq 0 python3 install_coagent.py --uninstall
echo.
pause
exit /b

:update
python install_coagent.py --update
if %errorlevel% neq 0 python3 install_coagent.py --update
pause
exit /b

:uninstall
python install_coagent.py --uninstall
if %errorlevel% neq 0 python3 install_coagent.py --uninstall
pause
exit /b

:status
python install_coagent.py --status
if %errorlevel% neq 0 python3 install_coagent.py --status
pause
exit /b

:help
echo CoAgent Installer - Commands:
echo.
echo   install_coagent.bat           Interactive menu
echo   install_coagent.bat --update  Update to latest
echo   install_coagent.bat --status  Check installation
echo   install_coagent.bat --uninstall Remove CoAgent
echo.
pause
exit /b
