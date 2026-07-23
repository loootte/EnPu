#Requires -Version 5.1
<#
.SYNOPSIS
  Start EnPu recognition core (FastAPI) for local development.
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
$VenvPip = Join-Path $CoreDir ".venv\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtualenv at core/.venv ..." -ForegroundColor Yellow
    python -m venv (Join-Path $CoreDir ".venv")
    if (-not (Test-Path $VenvPython)) {
        Write-Error "Failed to create venv. Is Python on PATH?"
    }
}

$Req = Join-Path $CoreDir "requirements.txt"
Write-Host "Ensuring dependencies from requirements.txt ..."
& $VenvPip install -q -r $Req
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed."
}

Set-Location $CoreDir
Write-Host "Starting uvicorn (reload)..." -ForegroundColor Green
& $VenvPython -m uvicorn app.main:app --reload --host $HostAddr --port $Port
