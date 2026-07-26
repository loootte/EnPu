#Requires -Version 5.1
<#
.SYNOPSIS
  Report Windows release artifact sizes (#81).

.DESCRIPTION
  Prints sidecar / UI / NSIS sizes and writes SIZE_REPORT.txt (UTF-8).
  Soft budgets (warning only):
    - enpu-core.exe  > 110 MB
    - NSIS setup     > 120 MB
#>
[CmdletBinding()]
param(
  [string]$OutDir = "",
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = $Root }
if (-not $ReportPath) {
  $ReportPath = Join-Path $OutDir "SIZE_REPORT.txt"
}

function Get-SizeRow([string]$Label, [string]$Path) {
  if (-not (Test-Path $Path)) {
    return [PSCustomObject]@{
      Label  = $Label
      Path   = $Path
      Bytes  = $null
      MB     = $null
      Exists = $false
    }
  }
  $item = Get-Item $Path
  return [PSCustomObject]@{
    Label  = $Label
    Path   = $item.FullName
    Bytes  = [int64]$item.Length
    MB     = [math]::Round($item.Length / 1MB, 2)
    Exists = $true
  }
}

$rows = @()
$core = Join-Path $Root "core\dist\enpu-core.exe"
$rows += Get-SizeRow "enpu-core.exe (sidecar)" $core

$binDir = Join-Path $Root "desktop\src-tauri\binaries"
$triple = Get-ChildItem -Path $binDir -Filter "enpu-core-*.exe" -ErrorAction SilentlyContinue |
  Sort-Object Length -Descending | Select-Object -First 1
if ($triple) {
  $rows += Get-SizeRow "enpu-core-*.exe (externalBin)" $triple.FullName
}

$app = Join-Path $Root "desktop\src-tauri\target\release\enpu-desktop.exe"
if (-not (Test-Path $app)) {
  $app = Join-Path $Root "desktop\src-tauri\target\release\EnPu.exe"
}
$rows += Get-SizeRow "EnPu desktop exe" $app

$nsisDir = Join-Path $Root "desktop\src-tauri\target\release\bundle\nsis"
$nsis = Get-ChildItem -Path $nsisDir -Filter "*.exe" -ErrorAction SilentlyContinue |
  Sort-Object Length -Descending | Select-Object -First 1
if ($nsis) {
  $rows += Get-SizeRow "NSIS setup" $nsis.FullName
} else {
  $rows += Get-SizeRow "NSIS setup" (Join-Path $nsisDir "(missing)")
}

$lines = @()
$lines += "EnPu Windows release size report (#81)"
$lines += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')"
$lines += ""
$lines += "Baseline before slim (approx): NSIS ~154 MB · sidecar ~152 MB"
$lines += "Soft targets: sidecar ≤110 MB · NSIS ≤120 MB (warn only)"
$lines += "Hard product goal: NSIS ≤100 MB when achievable; cv2.pyd dominates remainder"
$lines += ""
$lines += "{0,-32} {1,10} {2,12}" -f "Component", "MB", "Bytes"
$lines += ("-" * 58)

foreach ($r in $rows) {
  if ($r.Exists) {
    $line = "{0,-32} {1,10:N2} {2,12}" -f $r.Label, $r.MB, $r.Bytes
  } else {
    $line = "{0,-32} {1,10} {2,12}" -f $r.Label, "n/a", "-"
  }
  $lines += $line
  Write-Host $line
}

$lines += ""
$lines += "Notes:"
$lines += "- Default package = UI + mock sidecar (no PaddleOCR / models)."
$lines += "- Real OCR: post-install script or dev venv (see docs/release-windows.md)."
$lines += "- Sidecar build uses core/requirements-sidecar.txt + enpu-core.spec excludes."

$sidecar = $rows | Where-Object { $_.Label -like "enpu-core.exe*" } | Select-Object -First 1
$setup = $rows | Where-Object { $_.Label -eq "NSIS setup" } | Select-Object -First 1

$warns = @()
if ($sidecar -and $sidecar.Exists -and $sidecar.MB -gt 110) {
  $warns += "WARN: sidecar $($sidecar.MB) MB > 110 MB soft budget"
}
if ($setup -and $setup.Exists -and $setup.MB -gt 120) {
  $warns += "WARN: NSIS setup $($setup.MB) MB > 120 MB soft budget"
}
if ($setup -and $setup.Exists -and $setup.MB -gt 100) {
  $warns += "INFO: NSIS setup $($setup.MB) MB > 100 MB stretch goal (cv2.pyd bottleneck is expected)"
}

foreach ($w in $warns) {
  $lines += $w
  Write-Host $w -ForegroundColor Yellow
}

$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($ReportPath, $lines, $utf8)
Write-Host "`nWrote $ReportPath"
return $rows
