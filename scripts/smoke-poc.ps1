#Requires -Version 5.1
<#
.SYNOPSIS
  PoC smoke test: health + recognize sample (Issue #6).

.DESCRIPTION
  Verifies dual-process integration without the desktop UI.
  Requires core already running (start.ps1 / start.sh / dev-core.ps1).

.EXAMPLE
  .\scripts\start.ps1 -Engine mock -Ui none
  .\scripts\smoke-poc.ps1
  .\scripts\smoke-poc.ps1 -Engine paddleocr
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = $(if ($env:VITE_ENPU_CORE_URL) { $env:VITE_ENPU_CORE_URL } elseif ($env:ENPU_CORE_URL) { $env:ENPU_CORE_URL } else { "http://127.0.0.1:8765" }),
  [string]$Sample,
  [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Sample) {
  $Sample = Join-Path $Root "samples\001_poc_digits.png"
}
$BaseUrl = $BaseUrl.TrimEnd("/")

Write-Host "========================================"
Write-Host " EnPu PoC smoke"
Write-Host " base:   $BaseUrl"
Write-Host " sample: $Sample"
Write-Host "========================================"

if (-not (Test-Path $Sample)) {
  throw "Sample not found: $Sample"
}

# 1) Health
Write-Host "[1/2] GET /health ..."
try {
  $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 5
} catch {
  throw "Core not reachable at $BaseUrl. Start with: .\scripts\start.ps1  (or .\scripts\dev-core.ps1)"
}
Write-Host "      status=$($health.status) engine=$($health.engine) version=$($health.version)" -ForegroundColor Green
if ($health.status -ne "ok") { throw "Unexpected health status" }

# 2) Recognize
Write-Host "[2/2] POST /v1/recognize ..."
$py = Join-Path $Root "core\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  # fallback: system python + httpx may missing; use curl multipart if available
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if (-not $curl) { throw "Need core/.venv or curl.exe for multipart upload" }
  $tmpOut = Join-Path $env:TEMP "enpu-smoke.json"
  & curl.exe -sS -X POST "$BaseUrl/v1/recognize" -F "file=@$Sample" --max-time $TimeoutSec -o $tmpOut
  if ($LASTEXITCODE -ne 0) { throw "curl recognize failed" }
  $body = Get-Content $tmpOut -Raw | ConvertFrom-Json
} else {
  $tmpJson = Join-Path $env:TEMP "enpu-smoke-recognize.json"
  $code = @"
import httpx, pathlib, sys
base, path_s, timeout, out_s = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
path = pathlib.Path(path_s)
with path.open('rb') as f:
    r = httpx.post(base + '/v1/recognize', files={'file': (path.name, f, 'image/png')}, timeout=timeout)
pathlib.Path(out_s).write_text(r.text, encoding='utf-8')
print(r.status_code)
sys.exit(0 if r.status_code == 200 else 1)
"@
  $statusLine = & $py -c $code $BaseUrl $Sample $TimeoutSec $tmpJson
  if ($LASTEXITCODE -ne 0) {
    if (Test-Path $tmpJson) { Write-Host (Get-Content $tmpJson -Raw -Encoding UTF8) }
    throw "recognize failed (HTTP $statusLine)"
  }
  if ([int]$statusLine -ne 200) { throw "HTTP $statusLine" }
  $body = Get-Content $tmpJson -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (-not $body.ok) { throw "recognize ok=false: $($body | ConvertTo-Json -Compress)" }
$texts = @($body.texts)
Write-Host "      engine=$($body.engine) texts=$($texts.Count) elapsed_ms=$($body.meta.elapsed_ms)" -ForegroundColor Green
if ($texts.Count -gt 0) {
  Write-Host "      first texts: $($texts[0..([Math]::Min(2, $texts.Count-1))] -join ' | ')"
} else {
  Write-Host "[warn] texts empty (ocr may need paddle models)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "SMOKE PASSED" -ForegroundColor Green
Write-Host "Next: open desktop UI, import samples\001_poc_digits.png (or 002/003), click 开始识别."
Write-Host "Other: .\scripts\smoke-poc.ps1 -Sample .\samples\002_scan_like.png"
Write-Host "Checklist: docs\poc-acceptance.md"
Write-Host "========================================"
