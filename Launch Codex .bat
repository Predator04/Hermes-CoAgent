@echo off
setlocal enabledelayedexpansion
title ChatGPT Codex Terminal Launcher
color 0A

set "CONFIG_FILE=.codex_path"

echo =====================================
echo    ChatGPT Codex Terminal Launcher
echo =====================================

:: --- System Checks ---
where node >nul 2>nul || (echo Install Node.js first: https://nodejs.org && pause && exit /b)
where codex >nul 2>nul || (echo Installing Codex... && npm i -g @openai/codex)

:: --- Path Logic ---
if exist "%CONFIG_FILE%" (
    set /p PROJECT_PATH=<"%CONFIG_FILE%"
    goto :RUN_CODEX
)

:GET_PATH
echo.
set /p PROJECT_PATH=Enter Project Folder Path: 

if not exist "%PROJECT_PATH%" (
    echo [!] Folder not found.
    goto :GET_PATH
)

:: Save and hide the config file
echo %PROJECT_PATH%>"%CONFIG_FILE%"
attrib +h "%CONFIG_FILE%"

:RUN_CODEX
cls
echo =====================================
echo    ChatGPT Codex Terminal Launcher
echo =====================================
echo.
echo Launching in: %PROJECT_PATH%
echo.

cd /d "%PROJECT_PATH%"
codex

pause