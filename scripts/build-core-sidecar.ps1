#Requires -Version 5.1
<#
.SYNOPSIS
  Build EnPu core sidecar with PyInstaller (issue #8 PoC).
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Core = Join-Path $Root "core"
Set-Location $Core

$Py = Join-Path $Core ".venv\Scripts\python.exe"
$Pip = Join-Path $Core ".venv\Scripts\pip.exe"
if (-not (Test-Path $Py)) {
  Write-Host "Creating venv..."
  python -m venv .venv
}

Write-Host "Installing deps + PyInstaller..."
& $Pip install -q -U pip
& $Pip install -q -r requirements.txt
& $Pip install -q "pyinstaller>=6.0,<7"

Write-Host "Running PyInstaller..."
& $Py -m PyInstaller --noconfirm --clean enpu-core.spec

$out = Join-Path $Core "dist\enpu-core.exe"
if (-not (Test-Path $out)) {
  throw "Binary not found: $out"
}
$mb = [math]::Round((Get-Item $out).Length / 1MB, 2)
Write-Host "OK: $out ($mb MB)"
Write-Host "Smoke: & `"$out`" --engine mock --host 127.0.0.1 --port 8765"
