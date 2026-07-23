#Requires -Version 5.1
<#
.SYNOPSIS
  Start EnPu desktop (Tauri) for local development.

.DESCRIPTION
  Scaffold script for Phase 0. Full behavior after issue #4 scaffolds Tauri project.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $Root "desktop"

Write-Host "EnPu desktop dev launcher" -ForegroundColor Cyan
Write-Host "  root:    $Root"
Write-Host "  desktop: $DesktopDir"

if (-not (Test-Path $DesktopDir)) {
    Write-Error "desktop/ directory not found. Are you in the EnPu repo?"
}

$PackageJson = Join-Path $DesktopDir "package.json"
if (-not (Test-Path $PackageJson)) {
    Write-Host ""
    Write-Host "desktop/package.json not found — Tauri app not scaffolded yet." -ForegroundColor Yellow
    Write-Host "Implement in issue #4, then re-run: .\scripts\dev-desktop.ps1"
    Write-Host ""
    Write-Host "Target command:"
    Write-Host "  cd desktop"
    Write-Host "  npm install"
    Write-Host "  npm run tauri dev"
    Write-Host ""
    Write-Host "Remember to start core first (.\scripts\dev-core.ps1) for recognition."
    exit 2
}

Set-Location $DesktopDir

if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Host "node_modules missing — running npm install..." -ForegroundColor Yellow
    npm install
}

Write-Host "Starting Tauri dev..." -ForegroundColor Green
npm run tauri dev
