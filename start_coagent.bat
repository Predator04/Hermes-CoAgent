@echo off
cd /d "C:\Users\Admin\Desktop\Hermes CoAgent"
title CoAgent Launcher
echo Killing stale CoAgent processes...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
ping -n 4 127.0.0.1 >nul
echo Launching CoAgent...
start "" "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe" "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" --allow-external
echo CoAgent started - look for purple 'C' in system tray
ping -n 3 127.0.0.1 >nul
