# Test cursor pulse
$url = "http://localhost:9123"

try {
    $r = Invoke-RestMethod -Uri "$url/ping" -TimeoutSec 5
    Write-Output "Server: $($r.status) | Actions: $($r.actions_today)"
} catch {
    Write-Output "Server not running yet, waiting..."
    Start-Sleep 3
    $r = Invoke-RestMethod -Uri "$url/ping" -TimeoutSec 5
    Write-Output "Server: $($r.status)"
}

Write-Output "`n--- Testing cursor pulse (colored rings) ---"

# Move - should show GREEN ring
Write-Output "GREEN ring for move..."
Invoke-RestMethod -Uri "$url/mouse/move" -Method POST -Body (@{x=600; y=500} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
Start-Sleep 1

# Move to another spot
Write-Output "GREEN ring to (900, 500)..."
Invoke-RestMethod -Uri "$url/mouse/move" -Method POST -Body (@{x=900; y=500} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
Start-Sleep 1

# Click - should show ORANGE ring
Write-Output "ORANGE ring for click..."
Invoke-RestMethod -Uri "$url/mouse/click" -Method POST -Body (@{button="left"} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
Start-Sleep 1

# Scroll - should show YELLOW ring
Write-Output "YELLOW ring for scroll..."
Invoke-RestMethod -Uri "$url/mouse/scroll" -Method POST -Body (@{clicks=-3} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null
Start-Sleep 0.5

# Hotkey - should show MAGENTA ring
Write-Output "MAGENTA ring for hotkey..."
Invoke-RestMethod -Uri "$url/key/press" -Method POST -Body (@{keys=@("ctrl","v")} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null

Write-Output "`nDone! Check your desktop for colored rings."
Write-Output "Color guide: GREEN=move, ORANGE=click, YELLOW=scroll, MAGENTA=hotkey, BLUE=typing"
