$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$logDirectory = Join-Path $projectRoot "data\logs"
$logFile = Join-Path $logDirectory "daily-funnel.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Set-Location $projectRoot

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp] scheduled daily funnel starting"
& $python -m app.cli daily-funnel *>> $logFile
$exitCode = $LASTEXITCODE
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp] scheduled daily funnel finished with code $exitCode"
exit $exitCode
