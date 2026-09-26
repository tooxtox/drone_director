# 一键启动天枢智航后端（Windows PowerShell）
# 用法: .\scripts\run_backend.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv-runtime\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "未找到运行环境: $python，请先执行 scripts/setup.ps1"
    exit 1
}

Push-Location -LiteralPath $root
try {
    & $python -m backend.app
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
