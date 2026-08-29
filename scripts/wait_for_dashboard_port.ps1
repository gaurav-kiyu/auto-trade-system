<#
Polls a local TCP port until it accepts a connection, instead of guessing a
fixed delay before opening a browser to it.

Extracted out of start.bat/open_app.bat/open_admin.bat's inline
`powershell -Command "..."` one-liners: embedding a PowerShell snippet with
its own parentheses (for/if/New-Object) directly inside a batch `if (...)`
block confuses cmd.exe's parser ("... was unexpected at this time.") -
same class of bug as the multi-line `python -c "..."` blocks documented in
CHANGELOG.md v2.59.0 for scripts/run_paper_trading.bat.

Usage: powershell -NoProfile -File wait_for_dashboard_port.ps1 -Port 8765 [-OpenUrl http://localhost:8765/]

If -OpenUrl is supplied, opens it in the default browser once the port is
ready (used by start.bat, which has nothing else opening the browser).
Callers that already have their own unconditional "start <url>" line after
this script returns (open_app.bat/open_admin.bat) should omit -OpenUrl.
#>
param(
    [int]$Port = 8765,
    [int]$TimeoutSeconds = 60,
    [string]$OpenUrl = ""
)

$ready = $false
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    try {
        (New-Object System.Net.Sockets.TcpClient('127.0.0.1', $Port)).Close()
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($ready) {
    if ($OpenUrl) {
        Start-Process $OpenUrl
    }
} else {
    Write-Host "[WARN] Dashboard did not come up on port $Port within ${TimeoutSeconds}s - opening anyway, it may still be starting."
    if ($OpenUrl) {
        Start-Process $OpenUrl
    }
}
