#Requires -Version 5.1
<#
.SYNOPSIS
  Copy built enpu-core.exe into Tauri externalBin path with target triple suffix.

.DESCRIPTION
  Tauri 2 expects: desktop/src-tauri/binaries/enpu-core-<triple>.exe
  Issue #14 packaging pipeline.

.PARAMETER CoreExe
  Path to PyInstaller output (default: core/dist/enpu-core.exe)

.PARAMETER SkipBuild
  If set, do not invoke build-core-sidecar.ps1 when binary is missing.
#>
[CmdletBinding()]
param(
  [string]$CoreExe = "",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CoreDir = Join-Path $Root "core"
$BinDir = Join-Path $Root "desktop\src-tauri\binaries"

if (-not $CoreExe) {
  $CoreExe = Join-Path $CoreDir "dist\enpu-core.exe"
}

if (-not (Test-Path $CoreExe)) {
  if ($SkipBuild) {
    throw "Sidecar not found: $CoreExe (pass without -SkipBuild to build)"
  }
  Write-Host "[prepare-sidecar] Building core sidecar..."
  & (Join-Path $PSScriptRoot "build-core-sidecar.ps1")
  if (-not (Test-Path $CoreExe)) {
    throw "Build finished but binary missing: $CoreExe"
  }
}

# Resolve target triple for Tauri externalBin naming
$triple = $env:ENPU_TARGET_TRIPLE
if (-not $triple) {
  $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
  if (Test-Path (Join-Path $cargoBin "rustc.exe")) {
    $env:Path = "$cargoBin;$env:Path"
  }
  try {
    $triple = (& rustc --print host-tuple 2>$null | Out-String).Trim()
  } catch {}
  if (-not $triple) {
    try {
      $line = & rustc -Vv 2>$null | Select-String "host:"
      if ($line) { $triple = ($line.ToString() -split "\s+")[1] }
    } catch {}
  }
}
if (-not $triple) {
  $triple = "x86_64-pc-windows-msvc"
  Write-Host "[prepare-sidecar] rustc not found; default triple=$triple" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$dest = Join-Path $BinDir "enpu-core-$triple.exe"
Copy-Item -Force -Path $CoreExe -Destination $dest
$mb = [math]::Round((Get-Item $dest).Length / 1MB, 2)
Write-Host "[prepare-sidecar] OK: $dest ($mb MB)"
Write-Host "  tauri.conf.json externalBin: binaries/enpu-core"
return $dest
