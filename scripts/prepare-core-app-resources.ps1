#Requires -Version 5.1
<#
.SYNOPSIS
  Copy core/app + run_server.py into src-tauri/resources for NSIS / paddle launcher.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Core = Join-Path $Root "core"
$Dest = Join-Path $Root "desktop\src-tauri\resources\enpu-core-src"

if (-not (Test-Path (Join-Path $Core "app"))) {
  throw "core/app not found: $Core"
}

if (Test-Path $Dest) {
  Remove-Item -Recurse -Force $Dest
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item -Recurse -Force (Join-Path $Core "app") (Join-Path $Dest "app")
Copy-Item -Force (Join-Path $Core "run_server.py") (Join-Path $Dest "run_server.py")
# Drop __pycache__
Get-ChildItem -Path $Dest -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "OK: $Dest"
