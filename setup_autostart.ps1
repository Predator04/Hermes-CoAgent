$coagentDir = "$env:USERPROFILE\Desktop\Hermes CoAgent"
$scriptPath = "$coagentDir\start_hidden.vbs"
$trayScriptPath = "$coagentDir\start_tray_hidden.vbs"

$vbsContent = @"
CreateObject("Wscript.Shell").Run "cmd /c cd /d `"$coagentDir`" && python hermes_coagent.py 9123", 0, False
"@

Set-Content -Path $scriptPath -Value $vbsContent -Force

$trayVbsContent = @"
CreateObject("Wscript.Shell").Run """C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"" ""$coagentDir\coagent_tray.py""", 0, False
"@

Set-Content -Path $trayScriptPath -Value $trayVbsContent -Force

# Add both to Windows startup
$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Hermes CoAgent.lnk")
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$scriptPath`""
$shortcut.WindowStyle = 7
$shortcut.Description = "Hermes CoAgent v3 - Desktop Co-Pilot"
$shortcut.Save()

# Tray shortcut
$trayShortcut = $wshell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Hermes CoAgent Tray.lnk")
$trayShortcut.TargetPath = "wscript.exe"
$trayShortcut.Arguments = "`"$trayScriptPath`""
$trayShortcut.WindowStyle = 7
$trayShortcut.Description = "Hermes CoAgent Tray - System Tray Controls"
$trayShortcut.Save()

Write-Host "✅ Hermes CoAgent autostart installed"
Write-Host "  → Server starts minimized on Windows boot"
Write-Host "  → Tray icon appears by the clock"
Write-Host "  → Dashboard at http://localhost:9123"
Write-Host "  → Ctrl+Alt+Shift = emergency stop"
