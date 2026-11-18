param([ValidateRange(0, 10)][int]$StepDelay = 2)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$projectPath = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $PSScriptRoot 'demo_consistency.py'
$artifactPath = Join-Path $projectPath 'artifacts'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $artifactPath ("consistency-demo-" + $stamp + '.log')
$resultPath = Join-Path $artifactPath 'consistency-demo.json'
$marker = '@@ISSUEFLOW_DEMO_RESULT@@'
$lines = New-Object 'System.Collections.Generic.List[string]'
$resultJson = $null
Push-Location -LiteralPath $projectPath
try {
    Write-Host '正在准备 IssueFlow 并发与事务演示……' -ForegroundColor Cyan
    & docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) {
        throw '服务启动失败，请先打开 Docker Desktop，并确认项目 .env 已配置。'
    }
    New-Item -ItemType Directory -Path $artifactPath -Force | Out-Null
    Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8 |
        & docker compose exec -T -e PYTHONIOENCODING=utf-8 -e PYTHONUTF8=1 api python -u - --pace $StepDelay |
        ForEach-Object {
            $line = [string]$_
            if ($line.StartsWith($marker)) {
                $resultJson = $line.Substring($marker.Length)
            } else {
                $lines.Add($line)
                Write-Host $line
            }
        }
    $demoExit = $LASTEXITCODE
    $lines | Set-Content -LiteralPath $logPath -Encoding UTF8
    if ($demoExit -ne 0 -or -not $resultJson) {
        throw ('演示未通过；输出已保存：' + $logPath)
    }
    $resultJson | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ''
    Write-Host ('结果：' + $resultPath) -ForegroundColor Green
    Write-Host ('录屏文字：' + $logPath) -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
