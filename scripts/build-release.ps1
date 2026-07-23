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

# 3) Frontend deps + Tauri release bundle
Write-Host "`n[3/3] Tauri bundle (targets=$Targets)..." -ForegroundColor Cyan
Push-Location $Desktop
try {
  if (-not (Test-Path "node_modules")) {
    Write-Host "npm ci (first time)..."
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit $LASTEXITCODE" }
  }

  # Ensure sidecar externalBin is present (tauri build fails hard if missing)
  $binDir = Join-Path $Desktop "src-tauri\binaries"
  $sidecarBins = @(Get-ChildItem -Path $binDir -Filter "enpu-core-*.exe" -ErrorAction SilentlyContinue)
  if ($sidecarBins.Count -eq 0) {
    throw "No enpu-core-*.exe under desktop/src-tauri/binaries. Run prepare-sidecar.ps1 first."
  }
  Write-Host "  externalBin: $($sidecarBins[0].Name) ($([math]::Round($sidecarBins[0].Length/1MB,1)) MB)"

  $env:VITE_ENPU_CORE_URL = "http://127.0.0.1:8765"

  # IMPORTANT: arguments after the script name must follow `--`, otherwise npm
  # may swallow flags like --bundles and never run a real `tauri build`.
  # Correct:  npm run tauri -- build --bundles nsis
  # Wrong:    npm run tauri build --bundles nsis
  $tauriArgs = @("build")
  if ($Targets -eq "nsis") {
    $tauriArgs += @("--bundles", "nsis")
  } elseif ($Targets -eq "msi") {
    $tauriArgs += @("--bundles", "msi")
  }

  # Use cmd.exe so npm.cmd exit code is reliable (npm.ps1 + stderr noise is flaky).
  $argLine = ($tauriArgs | ForEach-Object {
      if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ }
    }) -join ' '
  $cmd = "npm run tauri -- $argLine"
  Write-Host $cmd
  cmd.exe /c $cmd
  if ($LASTEXITCODE -ne 0) {
    throw "tauri build failed with exit $LASTEXITCODE"
  }
} finally {
  Pop-Location
}

$releaseDir = Join-Path $Desktop "src-tauri\target\release"
$bundleRoot = Join-Path $releaseDir "bundle"
$mainExe = Join-Path $releaseDir "enpu-desktop.exe"

Write-Host "`n=== Done ===" -ForegroundColor Green
if (-not (Test-Path $releaseDir)) {
  throw @"
target/release was NOT created.

Common causes:
  1) cargo/rustc not on PATH in that shell (open a new terminal after rustup install)
  2) npm did not invoke tauri build (fixed: use 'npm run tauri -- build ...')
  3) build failed earlier — scroll up for cargo/tauri errors

Retry:
  `$env:Path = `"`$env:USERPROFILE\.cargo\bin;`$env:Path`"
  .\scripts\build-release.ps1 -SkipSidecarBuild
"@
}

Write-Host "  release dir: $releaseDir"
if (Test-Path $mainExe) {
  $mb = [math]::Round((Get-Item $mainExe).Length / 1MB, 2)
  Write-Host "  app: $mainExe ($mb MB)"
}

if (Test-Path $bundleRoot) {
  $found = Get-ChildItem -Recurse -File $bundleRoot -Include *.exe,*.msi,*.nsis.zip,*.zip -ErrorAction SilentlyContinue
  if ($found) {
    foreach ($f in $found) {
      $mb = [math]::Round($f.Length / 1MB, 2)
      Write-Host ("  bundle: {0}  ({1} MB)" -f $f.FullName, $mb)
    }
  } else {
    Write-Host "  (no nsis/msi under bundle — app exe may still be in target/release)" -ForegroundColor Yellow
  }
} else {
  Write-Host "  (bundle/ not found — if only enpu-desktop.exe exists, NSIS step may have failed)" -ForegroundColor Yellow
}
Write-Host "Docs: docs/release-windows.md"
exit 0
