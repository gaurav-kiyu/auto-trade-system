# Stops Python processes that are running the OPBuying index/stock option bots
# (matches command line containing the script filenames). Safe if nothing is running.
# Usage (PowerShell):  cd <repo>; .\scripts\stop_opbuying_bots.ps1

$ErrorActionPreference = "SilentlyContinue"
$markers = @(
    "INDEX_OPTION_BUYING_APP_1.0.py",
    "STOCK_OPTION_BUYING_APP_1.0.py"
)

foreach ($exe in @("python.exe", "python3.exe")) {
    Get-CimInstance Win32_Process -Filter "name='$exe'" | ForEach-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return }
        foreach ($m in $markers) {
            if ($cmd -like "*$m*") {
                Write-Host "Stopping PID $($_.ProcessId) ($exe) - $m"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                break
            }
        }
    }
}

Write-Host 'Done. If nothing was listed, no bot processes were running.'
