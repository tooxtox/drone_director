# 运行全部单元/集成测试（Windows PowerShell）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv-runtime\Scripts\python.exe"
& $python -m pytest $root
exit $LASTEXITCODE
