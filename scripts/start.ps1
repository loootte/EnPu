#Requires -Version 5.1
<#
.SYNOPSIS
  One-click start EnPu: core + Vite + desktop (Windows PowerShell).

.DESCRIPTION
  Background services use Hidden windows. Closing the desktop app can
  auto-stop core + UI (ENPU_AUTO_STOP=1, default).

.PARAMETER Ui
  both (default) | vite | none

.PARAMETER DesktopMode
  auto | exe | dev

.PARAMETER Engine
  paddleocr | mock

.EXAMPLE
  .\scripts\start.ps1
  .\scripts\start.ps1 -Engine mock
  .\scripts\start.ps1 -Ui vite
#>
[CmdletBinding()]
param(
  [ValidateSet("both", "vite", "none")]
  [string]$Ui = $(if ($env:ENPU_UI) { $env:ENPU_UI } else { "both" }),

  [ValidateSet("auto", "exe", "dev")]
  [string]$DesktopMode = $(if ($env:ENPU_DESKTOP_MODE) { $env:ENPU_DESKTOP_MODE } else { "auto" }),

  [ValidateSet("paddleocr", "mock")]
  [string]$Engine = $(if ($env:ENPU_RECOGNIZE_ENGINE) { $env:ENPU_RECOGNIZE_ENGINE } else { "paddleocr" }),

  [string]$CoreHost = $(if ($env:ENPU_CORE_HOST) { $env:ENPU_CORE_HOST } else { "127.0.0.1" }),
  [int]$CorePort = $(if ($env:ENPU_CORE_PORT) { [int]$env:ENPU_CORE_PORT } else { 8765 }),
  [int]$VitePort = $(if ($env:ENPU_VITE_PORT) { [int]$env:ENPU_VITE_PORT } else { 1420 }),

  [bool]$AutoStop = $(
    if ($null -ne $env:ENPU_AUTO_STOP -and $env:ENPU_AUTO_STOP -eq "0") { $false } else { $true }
  )
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "scripts\.run"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.env"
$CoreDir = Join-Path $Root "core"
$DesktopDir = Join-Path $Root "desktop"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-PidEntry([string]$Key, [int]$ProcessId) {
  if (-not (Test-Path $PidFile)) { "" | Set-Content -Path $PidFile -Encoding UTF8 }
  $lines = @(Get-Content $PidFile -ErrorAction SilentlyContinue | Where-Object { $_ -and $_ -notmatch "^${Key}=" })
  $lines += "${Key}=${ProcessId}"
  $lines | Set-Content -Path $PidFile -Encoding UTF8
}

function Test-PortListening([int]$Port) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return [bool]$c
}

function Wait-Http([string]$Url, [string]$Name, [int]$Retries = 40) {
  for ($i = 0; $i -lt $Retries; $i++) {
    try {
      $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) {
        Write-Host "[ok] $Name ready: $Url" -ForegroundColor Green
        return $true
      }
    } catch {
      try {
        # /health returns JSON; 200 only
        $null = Invoke-RestMethod -Uri $Url -TimeoutSec 1
        Write-Host "[ok] $Name ready: $Url" -ForegroundColor Green
        return $true
      } catch {}
    }
    Start-Sleep -Milliseconds 500
  }
  Write-Host "[warn] $Name not ready: $Url" -ForegroundColor Yellow
  return $false
}

function Ensure-CoreVenv {
  $py = Join-Path $CoreDir ".venv\Scripts\python.exe"
  $pip = Join-Path $CoreDir ".venv\Scripts\pip.exe"
  if (-not (Test-Path $py)) {
    Write-Host "[core] creating venv..."
    python -m venv (Join-Path $CoreDir ".venv")
  }
  Write-Host "[core] ensuring pip deps..."
  & $pip install -q -U pip
  & $pip install -q -r (Join-Path $CoreDir "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  return $py
}

function Start-Core {
  if (Test-PortListening $CorePort) {
    try {
      $null = Invoke-RestMethod "http://${CoreHost}:${CorePort}/health" -TimeoutSec 2
      Write-Host "[core] already running on :$CorePort"
      return
    } catch {
      throw "Port $CorePort busy but /health failed. Run .\scripts\stop.ps1 first."
    }
  }
  $py = Ensure-CoreVenv
  $log = Join-Path $LogDir "core.log"
  "" | Set-Content $log -ErrorAction SilentlyContinue
  Write-Host "[core] starting uvicorn ($Engine) — no console"
  # Hidden cmd avoids PowerShell dual-redirect file locks
  $arg = "/c set ENPU_RECOGNIZE_ENGINE=$Engine&& `"$py`" -m uvicorn app.main:app --host $CoreHost --port $CorePort >> `"$log`" 2>&1"
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList $arg -WorkingDirectory $CoreDir -WindowStyle Hidden -PassThru
  Write-PidEntry "CORE_PID" $p.Id
  Write-Host "[core] pid=$($p.Id)  log=$log"
  [void](Wait-Http "http://${CoreHost}:${CorePort}/health" "core" 60)
}

function Ensure-Npm {
  if (-not (Test-Path (Join-Path $DesktopDir "node_modules"))) {
    Write-Host "[ui] npm install..."
    Push-Location $DesktopDir
    try { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install failed" } }
    finally { Pop-Location }
  }
}

function Start-Vite {
  if (Test-PortListening $VitePort) {
    Write-Host "[vite] already running on :$VitePort"
    return
  }
  Ensure-Npm
  $log = Join-Path $LogDir "vite.log"
  "" | Set-Content $log
  Write-Host "[vite] starting http://localhost:$VitePort — no console"
  $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
  if (-not $npm) { $npm = "npm.cmd" }
  # cmd /c keeps npm.cmd happy; Hidden console
  $arg = "/c `"npm run dev -- --host localhost --port $VitePort >> `"$log`" 2>&1`""
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList $arg -WorkingDirectory $DesktopDir -WindowStyle Hidden -PassThru
  Write-PidEntry "VITE_PID" $p.Id
  Write-Host "[vite] pid=$($p.Id)  log=$log"
  [void](Wait-Http "http://localhost:${VitePort}/" "vite" 40)
}

function Get-DesktopExe {
  @(
    (Join-Path $DesktopDir "src-tauri\target\debug\enpu-desktop.exe"),
    (Join-Path $DesktopDir "src-tauri\target\release\enpu-desktop.exe")
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Start-DesktopExe {
  $exe = Get-DesktopExe
  if (-not $exe) { return $false }
  if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
    Write-Host "[desktop] already running"
    return $true
  }
  Write-Host "[desktop] launching $exe"
  $p = Start-Process -FilePath $exe -WorkingDirectory $DesktopDir -WindowStyle Normal -PassThru
  Write-PidEntry "DESKTOP_PID" $p.Id
  Start-Sleep -Seconds 1
  if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
    Write-Host "[ok] desktop window up" -ForegroundColor Green
    return $true
  }
  Write-Host "[warn] desktop not detected" -ForegroundColor Yellow
  return $true
}

function Start-DesktopDev {
  Ensure-Npm
  $cargo = Join-Path $env:USERPROFILE ".cargo\bin"
  if (Test-Path $cargo) { $env:Path = "$cargo;$env:Path" }
  if (-not (Get-Command rustc -ErrorAction SilentlyContinue) -and -not (Get-DesktopExe)) {
    Write-Host "[desktop] no rustc and no prebuilt exe — skip"
    return
  }
  if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
    Write-Host "[desktop] already running"
    return
  }
  $override = Join-Path $DesktopDir "tauri.dev.override.json"
  @"
{
  "build": {
    "beforeDevCommand": "",
    "devUrl": "http://localhost:$VitePort"
  }
}
"@ | Set-Content -Path $override -Encoding UTF8

  $log = Join-Path $LogDir "tauri.log"
  "" | Set-Content $log
  Write-Host "[desktop] starting tauri dev — no console"
  $vsDev = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"
  if (Test-Path $vsDev) {
    $inner = "call `"$vsDev`" -arch=x64 >nul 2>&1 && set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cd /d `"$DesktopDir`" && npx tauri dev --config tauri.dev.override.json >> `"$log`" 2>&1"
  } else {
    $inner = "set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cd /d `"$DesktopDir`" && npx tauri dev --config tauri.dev.override.json >> `"$log`" 2>&1"
  }
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $inner) -WindowStyle Hidden -PassThru
  Write-PidEntry "TAURI_PID" $p.Id
  for ($i = 0; $i -lt 45; $i++) {
    if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
      Write-Host "[ok] desktop window up" -ForegroundColor Green
      return
    }
    Start-Sleep -Seconds 1
  }
  Write-Host "[warn] desktop not detected — see $log" -ForegroundColor Yellow
}

function Start-Desktop {
  Start-Vite
  $mode = $DesktopMode
  if ($mode -eq "auto") {
    $mode = if (Get-DesktopExe) { "exe" } else { "dev" }
  }
  if ($mode -eq "exe") {
    if (-not (Start-DesktopExe)) { Start-DesktopDev }
  } else {
    Start-DesktopDev
  }
}

function Start-DesktopWatcher {
  if (-not $AutoStop) {
    Write-Host "[watch] auto-stop disabled"
    return
  }
  $found = $false
  for ($i = 0; $i -lt 60; $i++) {
    if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) { $found = $true; break }
    Start-Sleep -Seconds 1
  }
  if (-not $found) {
    Write-Host "[watch] desktop never appeared — watcher not armed" -ForegroundColor Yellow
    return
  }
  Write-Host "[watch] armed: close desktop → stop core + UI"
  $watcher = Join-Path $PSScriptRoot "desktop-watcher.ps1"
  $log = Join-Path $LogDir "watcher.log"
  $p = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
    "-File", $watcher,
    "-RepoRoot", $Root,
    "-LogPath", $log,
    "-CorePort", "$CorePort",
    "-VitePort", "$VitePort"
  ) -WindowStyle Hidden -PassThru
  Write-PidEntry "WATCHER_PID" $p.Id
  Write-Host "[watch] pid=$($p.Id)  log=$log"
}

# --- main ---
Write-Host "========================================"
Write-Host " EnPu start (PowerShell)"
Write-Host " root:      $Root"
Write-Host " ui:        $Ui"
Write-Host " desktop:   $DesktopMode"
Write-Host " engine:    $Engine"
Write-Host " auto-stop: $AutoStop"
Write-Host "========================================"

"" | Set-Content -Path $PidFile -Encoding UTF8
Start-Core

switch ($Ui) {
  "vite" { Start-Vite }
  "both" {
    Start-Desktop
    Start-DesktopWatcher
  }
  "none" { Write-Host "[ui] skipped" }
}

Write-Host ""
Write-Host "Started." -ForegroundColor Cyan
Write-Host "  Core:     http://${CoreHost}:${CorePort}/health"
Write-Host "  Docs:     http://${CoreHost}:${CorePort}/docs"
if ($Ui -in @("vite", "both")) {
  Write-Host "  Web UI:   http://localhost:${VitePort}"
}
if ($Ui -eq "both") {
  Write-Host "  Desktop:  EnPu window"
  if ($AutoStop) { Write-Host "  Auto-stop: close desktop → core + UI stop" }
}
Write-Host "  Logs:     $LogDir"
Write-Host "Stop with:  .\scripts\stop.ps1"
Write-Host "Smoke:      .\scripts\smoke-poc.ps1"
Write-Host "========================================"
