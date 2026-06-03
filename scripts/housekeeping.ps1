# OPB Trading Platform Housekeeping — v2.53.0
param(
    [switch]$WhatIfMode
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$targets = @(
    (Join-Path $root "__pycache__"),
    (Join-Path $root ".pytest_cache"),
    (Join-Path $root "tests\__pycache__"),
    (Join-Path $root "core\__pycache__"),
    (Join-Path $root "index_app\__pycache__"),
    (Join-Path $root "scripts\__pycache__"),
    (Join-Path $root "tg_fallback_alerts.log"),
    (Join-Path $root "index_trader_gui_layout.json")
)

$patterns = @(
    "*.tmp",
    "_regression_bad_stock_config.json"
)

Write-Host "Housekeeping root: $root"

foreach ($target in $targets) {
    if (Test-Path -LiteralPath $target) {
        if ($WhatIfMode) {
            Write-Host "[whatif] remove $target"
        } else {
            Remove-Item -LiteralPath $target -Recurse -Force
            Write-Host "removed $target"
        }
    }
}

foreach ($pattern in $patterns) {
    Get-ChildItem -LiteralPath $root -Filter $pattern -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($WhatIfMode) {
            Write-Host "[whatif] remove $($_.FullName)"
        } else {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
            Write-Host "removed $($_.FullName)"
        }
    }
}

foreach ($folder in @("logs", "backups", "reports")) {
    $path = Join-Path $root $folder
    if (-not (Test-Path -LiteralPath $path)) {
        continue
    }
    Get-ChildItem -LiteralPath $path -Force -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($WhatIfMode) {
            Write-Host "[whatif] remove $($_.FullName)"
        } else {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Host "removed $($_.FullName)"
        }
    }
    if ($folder -eq "reports") {
        Get-ChildItem -LiteralPath $path -Directory -Filter "_tmp*" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            if ($WhatIfMode) {
                Write-Host "[whatif] remove $($_.FullName)"
            } else {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force
                Write-Host "removed $($_.FullName)"
            }
        }
    }
}

Write-Host "housekeeping complete"
