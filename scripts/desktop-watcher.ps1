# Watches enpu-desktop; when it exits, runs scripts/stop.sh (no console).
# Invoked hidden by start.sh on Windows.
param(
  [Parameter(Mandatory = $true)][string]$RepoRoot,
  [Parameter(Mandatory = $true)][string]$LogPath,
  [int]$CorePort = 8765,
  [int]$VitePort = 1420
)

$ErrorActionPreference = "SilentlyContinue"
function Log([string]$msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $LogPath -Value "[$ts] $msg" -Encoding UTF8
}

Log "watcher start; waiting for enpu-desktop"
$found = $false
for ($i = 0; $i -lt 120; $i++) {
  if (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
    $found = $true
    break
  }
  Start-Sleep -Seconds 1
}
if (-not $found) {
  Log "desktop never appeared; exit"
  exit 0
}

Log "desktop running; waiting for close"
while (Get-Process -Name "enpu-desktop" -ErrorAction SilentlyContinue) {
  Start-Sleep -Seconds 2
}

Log "desktop closed; stopping core + ui"
$bash = "C:\Program Files\Git\bin\bash.exe"
$stopSh = Join-Path $RepoRoot "scripts\stop.sh"
if (Test-Path $bash) {
  # Convert to Git Bash path: D:\foo -> /d/foo
  $drive = $RepoRoot.Substring(0, 1).ToLowerInvariant()
  $rest = $RepoRoot.Substring(2).Replace("\", "/")
  $unixRoot = "/$drive$rest"
  & $bash -lc "cd '$unixRoot' && ./scripts/stop.sh --from-watcher" 2>&1 | ForEach-Object { Log "$_" }
} else {
  Log "git bash not found; fallback port kill"
  foreach ($port in @($CorePort, $VitePort)) {
    Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  }
  Stop-Process -Name "enpu-desktop" -Force -ErrorAction SilentlyContinue
}
Log "watcher done"
exit 0
