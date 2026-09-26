param([int]$BackendPort = 8011, [int]$FrontendPort = 5173)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv-runtime/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "请先执行 scripts/setup.ps1" }
foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $port 已被占用。可指定 -BackendPort 8012 -FrontendPort 5174。"
    }
}
$logDirectory = Join-Path $projectRoot "data/logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$backend = Start-Process -FilePath $python -ArgumentList @("-X", "utf8", "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "$BackendPort") -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory "backend.out.log") -RedirectStandardError (Join-Path $logDirectory "backend.err.log")
Write-Host "后端进程 PID: $($backend.Id)，前端地址 http://127.0.0.1:$FrontendPort"
Write-Host "退出本脚本会停止本次启动的后端。进入网页后点击“生成 100 机演示”。"
try {
    & (Join-Path $PSScriptRoot "run_frontend.ps1") -Port $FrontendPort -BackendPort $BackendPort
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id }
}
