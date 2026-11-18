param([switch]$Install)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    $randomBytes = New-Object byte[] 48
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $randomGenerator.GetBytes($randomBytes)
    $randomGenerator.Dispose()
    $envText = [regex]::Replace([IO.File]::ReadAllText((Join-Path $projectPath '.env')), '(?m)^JWT_SECRET=.*$', ('JWT_SECRET=' + [Convert]::ToBase64String($randomBytes)))
    [IO.File]::WriteAllText((Join-Path $projectPath '.env'), $envText)
}
if ($Install -or -not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    & ./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
    Push-Location frontend
    npm ci
    Pop-Location
}
docker compose up -d --wait db
if ($LASTEXITCODE -ne 0) { throw '请先启动 Docker Desktop' }
Push-Location backend
& ../.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败' }
& ../.venv/Scripts/python.exe -m app.cli seed
Pop-Location
Push-Location frontend
npm run build
if ($LASTEXITCODE -ne 0) { throw '页面构建失败' }
Pop-Location
$apiProcess = Start-Process -FilePath (Join-Path $projectPath '.venv/Scripts/python.exe') -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8010','--no-access-log' -WorkingDirectory (Join-Path $projectPath 'backend') -WindowStyle Hidden -PassThru
Write-Host 'IssueFlow: http://localhost:3000  API: http://127.0.0.1:8010/docs'
try {
    Set-Location (Join-Path $projectPath 'frontend')
    npm start
} finally {
    if (-not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
    Set-Location -LiteralPath $projectPath
}
