param(
    [string]$CuaExe = (Join-Path $env:USERPROFILE 'AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe'),
    [switch]$Overlay
)

$ErrorActionPreference = 'Stop'

if ($Overlay) {
    & $CuaExe mcp
} else {
    & $CuaExe mcp --no-overlay
}
exit $LASTEXITCODE
