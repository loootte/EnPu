#Requires -Version 5.1
<#
.SYNOPSIS
  Start EnPu recognition core (FastAPI) for local development.

.DESCRIPTION
  Scaffold script for Phase 0. Full behavior after issue #2 implements app.main:app.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CoreDir = Join-Path $Root "core"
$Port = if ($env:ENPU_CORE_PORT) { $env:ENPU_CORE_PORT } else { "8765" }
$HostAddr = if ($env:ENPU_CORE_HOST) { $env:ENPU_CORE_HOST } else { "127.0.0.1" }

Write-Host "EnPu core dev launcher" -ForegroundColor Cyan
Write-Host "  root: $Root"
Write-Host "  core: $CoreDir"
Write-Host "  url:  http://${HostAddr}:${Port}"

if (-not (Test-Path $CoreDir)) {
    Write-Error "core/ directory not found. Are you in the EnPu repo?"
}

$VenvPython = Join-Path $CoreDir ".venv\Scripts\python.exe"
$MainPy = Join-Path $CoreDir "app\main.py"

if (-not (Test-Path $VenvPython)) {
    Write-Host ""
    Write-Host "Virtualenv not found. Create it first:" -ForegroundColor Yellow
    Write-Host "  cd core"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pip install -r requirements.txt"
    Write-Host ""
    Write-Host "Then re-run: .\scripts\dev-core.ps1"
    exit 1
}

# Detect scaffold placeholder (raises SystemExit on import/run until #2)
$probe = & $VenvPython -c "import pathlib; p=pathlib.Path(r'$MainPy'); print(p.read_text(encoding='utf-8')[:80])" 2>$null
if ($probe -match "Scaffold|issue #2|SystemExit") {
    Write-Host ""
    Write-Host "core/app/main.py is still a scaffold." -ForegroundColor Yellow
    Write-Host "Implement FastAPI in issue #2, then this script will start uvicorn."
    Write-Host ""
    Write-Host "Target command:"
    Write-Host "  cd core"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  uvicorn app.main:app --reload --host $HostAddr --port $Port"
    exit 2
}

Set-Location $CoreDir
Write-Host "Starting uvicorn..." -ForegroundColor Green
& $VenvPython -m uvicorn app.main:app --reload --host $HostAddr --port $Port
