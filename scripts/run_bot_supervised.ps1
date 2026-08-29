<#
Runs the trading bot as a supervised child process so that closing THIS
console window (or Ctrl+C) stops the bot immediately, instead of leaving an
orphaned python.exe running invisibly in the background - the exact failure
mode found 2026-08-22: start.bat's window appeared to close, but its
foreground child process kept running undetected, and repeated launches
piled up multiple concurrent bot instances writing to the same SQLite DBs.

Mechanism: PowerShell.Exiting is the documented engine event that fires
when this console window is closed (or `exit` is run) - registering a
handler on it to stop the child process is the standard way to tie a
child's lifetime to its parent console's, without needing a native
Job-Object helper. A polling loop (not a single blocking Wait-Process call)
is used so the engine keeps getting chances to dispatch that queued event.
#>
param(
    [string]$PythonExe = "py",
    [string]$ScriptPath = "index_app\index_trader.py",
    [string[]]$ScriptArgs = @("--paper")
)

$proc = Start-Process -FilePath $PythonExe -ArgumentList (@($ScriptPath) + $ScriptArgs) -NoNewWindow -PassThru

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Get-Process -Id $Event.MessageData -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
} -MessageData $proc.Id | Out-Null

try {
    while (-not $proc.HasExited) {
        Start-Sleep -Milliseconds 500
    }
} finally {
    if ($proc -and -not $proc.HasExited) {
        Write-Host "[CLEANUP] Stopping bot process (PID $($proc.Id))..."
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

exit $proc.ExitCode
