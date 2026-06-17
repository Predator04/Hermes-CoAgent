param([string]$OutputPath = "C:\Temp\_coagent_screen.png")
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
$dir = Split-Path $OutputPath -Parent
if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $b.Size)
$bmp.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output $OutputPath
