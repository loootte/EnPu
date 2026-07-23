#Requires -Version 5.1
<#
.SYNOPSIS
  Build Windows release: core sidecar + Tauri NSIS/MSI installer (issue #14).

.DESCRIPTION
  1. PyInstaller enpu-core.exe (mock engine by default)
  2. prepare-sidecar → src-tauri/binaries/enpu-core-<triple>.exe
  3. npm ci / npm run tauri build
  4. Print artifact paths under desktop/src-tauri/target/release/bundle/

.PARAMETER Engine
  Sidecar default engine baked via build-time env (runtime still overridable by CLI).
  Packaging uses mock for offline-friendly installers.

.PARAMETER Targets
  Tauri bundle targets: nsis | msi | all (default nsis)

.PARAMETER SkipSidecarBuild
  Reuse existing core/dist/enpu-core.exe

.EXAMPLE
  .\scripts\build-release.ps1
  .\scripts\build-release.ps1 -Targets nsis -SkipSidecarBuild
#>
[CmdletBinding()]
param(
  [ValidateSet("mock", "paddleocr")]
  [string]$Engine = "mock",

  [ValidateSet("nsis", "msi", "all")]
  [string]$Targets = "nsis",

  [switch]$SkipSidecarBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Root "desktop"
$CargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path (Join-Path $CargoBin "cargo.exe")) {
  $env:Path = "$CargoBin;$env:Path"
}

function Assert-Cmd([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $Name"
  }
}

Write-Host "=== EnPu Windows release build (#14) ===" -ForegroundColor Cyan
Assert-Cmd "node"
Assert-Cmd "npm"
Assert-Cmd "cargo"
Assert-Cmd "rustc"

# 1) Sidecar
if (-not $SkipSidecarBuild) {
  Write-Host "`n[1/3] Build core sidecar (engine default=$Engine)..." -ForegroundColor Cyan
  $env:ENPU_RECOGNIZE_ENGINE = $Engine
  & (Join-Path $PSScriptRoot "build-core-sidecar.ps1")
} else {
  Write-Host "`n[1/3] Skip sidecar build (reuse existing)" -ForegroundColor Yellow
}

Write-Host "`n[2/3] Prepare Tauri externalBin..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "prepare-sidecar.ps1") -SkipBuild

# 2) Frontend deps + Tauri bundle
Write-Host "`n[3/3] Tauri bundle (targets=$Targets)..." -ForegroundColor Cyan
Push-Location $Desktop
try {
  if (-not (Test-Path "node_modules")) {
    npm ci
  }
  $env:VITE_ENPU_CORE_URL = "http://127.0.0.1:8765"
  # Limit bundle targets via env (tauri 2 supports TAURI_BUNDLE_TARGETS in some versions)
  # Prefer CLI flag when available:
  $bundleArgs = @("run", "tauri", "build")
  if ($Targets -eq "nsis") {
    $bundleArgs += @("--bundles", "nsis")
  } elseif ($Targets -eq "msi") {
    $bundleArgs += @("--bundles", "msi")
  }
  # else all from tauri.conf.json
  Write-Host "npm $($bundleArgs -join ' ')"
  & npm @bundleArgs
  if ($LASTEXITCODE -ne 0) { throw "tauri build failed with exit $LASTEXITCODE" }
} finally {
  Pop-Location
}

$bundleRoot = Join-Path $Desktop "src-tauri\target\release\bundle"
Write-Host "`n=== Done ===" -ForegroundColor Green
if (Test-Path $bundleRoot) {
  Get-ChildItem -Recurse -File $bundleRoot -Include *.exe,*.msi,*.nsis.zip,*.zip -ErrorAction SilentlyContinue |
    ForEach-Object {
      $mb = [math]::Round($_.Length / 1MB, 2)
      Write-Host ("  {0}  ({1} MB)" -f $_.FullName, $mb)
    }
} else {
  Write-Host "  (bundle dir not found — check tauri build logs)" -ForegroundColor Yellow
}
Write-Host "Docs: docs/release-windows.md"
