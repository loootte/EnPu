#Requires -Version 5.1
<#
.SYNOPSIS
  One-click stop EnPu core / Vite / desktop (Windows PowerShell).

.EXAMPLE
  .\scripts\stop.ps1
  .\scripts\stop.ps1 -PortsOnly
#>
[CmdletBinding()]
param(
  [switch]$PortsOnly,
  [switch]$FromWatcher,
  [int]$CorePort = $(if ($env:ENPU_CORE_PORT) { [int]$env:ENPU_CORE_PORT } else { 8765 }),
  [int]$VitePort = $(if ($env:ENPU_VITE_PORT) { [int]$env:ENPU_VITE_PORT } else { 1420 })
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "scripts\.run"
$PidFile = Join-Path $RunDir "pids.env"
$LogDir = Join-Path $RunDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Stop-PidSafe([int]$ProcessId, [string]$Label) {
  if ($ProcessId -le 0) { return }
  $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $proc) {
    Write-Host "[skip] ${Label}=${ProcessId} not running"
    return
  }
  Write-Host "[stop] ${Label}=${ProcessId}"
  # Kill process tree on Windows
  taskkill /PID $ProcessId /T /F 2>$null | Out-Null
  Start-Sleep -Milliseconds 200
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-Port([int]$Port) {
  $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (-not $conns) {
    Write-Host "[port] :${Port} free"
    return
  }
  $conns | ForEach-Object {
    Stop-PidSafe -ProcessId $_.OwningProcess -Label "port:${Port}"
  }
}

if ($FromWatcher) {
  $msg = "[stop] triggered by desktop close watcher"
  Write-Host $msg
  Add-Content -Path (Join-Path $LogDir "watcher.log") -Value $msg -ErrorAction SilentlyContinue
}

Write-Host "========================================"
Write-Host " EnPu stop (PowerShell)"
Write-Host "========================================"

$watcherPid = $null
if (-not $PortsOnly -and (Test-Path $PidFile)) {
  Write-Host "[pids] reading $PidFile"
  Get-Content $PidFile | ForEach-Object {
    if ($_ -match "^(CORE_PID|VITE_PID|TAURI_PID|DESKTOP_PID|WATCHER_PID)=(\d+)$") {
      $key = $Matches[1]
      $id = [int]$Matches[2]
      if ($key -eq "WATCHER_PID") {
        $watcherPid = $id
      } else {
        Stop-PidSafe -ProcessId $id -Label $key
      }
    }
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
} else {
  if ($PortsOnly) { Write-Host "[mode] PortsOnly" }
  else { Write-Host "[pids] no pid file" }
}

Stop-Port $CorePort
Stop-Port $VitePort
Stop-Process -Name "enpu-desktop" -Force -ErrorAction SilentlyContinue

if ($watcherPid -and -not $FromWatcher) {
  Stop-PidSafe -ProcessId $watcherPid -Label "WATCHER_PID"
}

Write-Host ""
Write-Host "Stopped (core :$CorePort, vite :$VitePort, desktop)."
Write-Host "========================================"
