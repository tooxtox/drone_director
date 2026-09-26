$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".venv-runtime"
    & uv sync --locked --group dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (Test-Path "frontend/package-lock.json") {
        & npm.cmd --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally { Pop-Location }
