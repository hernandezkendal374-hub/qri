$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "data\logs"
$logFile = Join-Path $logDirectory "daily-funnel.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Set-Location $projectRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp] scheduled daily funnel starting"
if (-not (Test-Path -LiteralPath $python)) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] scheduled daily funnel failed: project virtual environment not found at $python"
    exit 1
}

& $python -m app.cli daily-funnel *>> $logFile
$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp] scheduled daily funnel finished with code $exitCode"
exit $exitCode
