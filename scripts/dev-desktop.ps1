#Requires -Version 5.1
<#
.SYNOPSIS
  Start EnPu desktop (Tauri) for local development.
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
    Write-Error "desktop/package.json missing."
}

# Ensure cargo on PATH when launched from fresh shells
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) {
    $env:Path = "$cargoBin;" + $env:Path
}

Set-Location $DesktopDir

if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Host "node_modules missing — running npm install..." -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed" }
}

if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Write-Host "Rust (rustc) not found on PATH." -ForegroundColor Yellow
    Write-Host "Install from https://rustup.rs/ then re-open the terminal."
    exit 1
}

Write-Host "Starting Tauri dev (first compile may take several minutes)..." -ForegroundColor Green
Write-Host "Tip: start core separately with .\scripts\dev-core.ps1"
npm run tauri dev
