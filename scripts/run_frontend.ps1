param([int]$Port = 5173, [int]$BackendPort = 8011)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:TS_API_TARGET = "http://127.0.0.1:$BackendPort"
Push-Location -LiteralPath (Join-Path $projectRoot "frontend")
try {
    & npm.cmd run dev -- --port $Port
    exit $LASTEXITCODE
} finally { Pop-Location }
