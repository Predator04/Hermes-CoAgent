param(
    [string]$CuaExe = 'C:\Users\Admin\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe',
    [switch]$Overlay
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $CuaExe -PathType Leaf)) {
    $resolved = Get-Command cua-driver.exe -ErrorAction SilentlyContinue
    if ($resolved -and $resolved.Source) {
        $CuaExe = $resolved.Source
    } else {
        [Console]::Error.WriteLine("cua_mcp_bridge: cua-driver.exe not found at '$CuaExe' or on PATH")
        exit 127
    }
}

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $CuaExe
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$bridgeArgs = @('mcp')
if (-not $Overlay) {
    $bridgeArgs += '--no-overlay'
}
$psi.Arguments = $bridgeArgs -join ' '

$proc = [System.Diagnostics.Process]::new()
$proc.StartInfo = $psi

try {
    [void]$proc.Start()

    $stdin = [Console]::OpenStandardInput()
    $stdout = [Console]::OpenStandardOutput()
    $stderr = [Console]::OpenStandardError()

    $stdinTask = $stdin.CopyToAsync($proc.StandardInput.BaseStream)
    $stdoutTask = $proc.StandardOutput.BaseStream.CopyToAsync($stdout)
    $stderrTask = $proc.StandardError.BaseStream.CopyToAsync($stderr)

    $stdinTask.ContinueWith({
        param($task, $state)
        try {
            $state.Close()
        } catch {
        }
    }, $proc.StandardInput) > $null

    $proc.WaitForExit()

    try {
        [System.Threading.Tasks.Task]::WaitAll(@($stdoutTask, $stderrTask), 1000) > $null
    } catch {
    }

    exit $proc.ExitCode
} catch {
    [Console]::Error.WriteLine("cua_mcp_bridge: $($_.Exception.Message)")
    try {
        if (-not $proc.HasExited) {
            $proc.Kill()
        }
    } catch {
    }
    exit 1
}
