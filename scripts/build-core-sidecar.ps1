#Requires -Version 5.1
<#
.SYNOPSIS
  Build EnPu core sidecar with PyInstaller (issue #8 / #14 / #81).

.DESCRIPTION
  Installs **requirements-sidecar.txt** (no Paddle) into core/.venv by default
  so the release binary stays lean. Use -FullDeps only when you intentionally
  want the full OCR venv (still excludes Paddle from the frozen binary).

.PARAMETER FullDeps
  Install core/requirements.txt (includes Paddle) instead of requirements-sidecar.txt.
#>
[CmdletBinding()]
param(
  [switch]$FullDeps
)

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

$req = if ($FullDeps) { "requirements.txt" } else { "requirements-sidecar.txt" }
Write-Host "Installing deps ($req) + PyInstaller..."
& $Pip install -q -U pip
& $Pip install -q -r $req
& $Pip install -q "pyinstaller>=6.0,<7"

Write-Host "Running PyInstaller (enpu-core.spec, slim excludes #81)..."
& $Py -m PyInstaller --noconfirm --clean enpu-core.spec

$out = Join-Path $Core "dist\enpu-core.exe"
if (-not (Test-Path $out)) {
  throw "Binary not found: $out"
}
$bytes = (Get-Item $out).Length
$mb = [math]::Round($bytes / 1MB, 2)
Write-Host "OK: $out ($mb MB / $bytes bytes)"
Write-Host "Smoke: & `"$out`" --engine mock --host 127.0.0.1 --port 8765"

# Soft budget from #81 (warning only — cv2.pyd dominates on Windows)
$warnMb = 110
if ($mb -gt $warnMb) {
  Write-Host "WARN: sidecar $mb MB > soft target ${warnMb}MB (see docs/release-windows.md)" -ForegroundColor Yellow
}
