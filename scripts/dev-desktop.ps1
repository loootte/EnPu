#Requires -Version 5.1
<#
.SYNOPSIS
  Start EnPu desktop (Tauri) for local development.

.NOTES
  On Windows, Tauri/Rust targets x86_64-pc-windows-msvc and needs MSVC ``link.exe``.
  Miniconda/Git often put a Unix ``link.exe`` earlier on PATH, which fails with:

    /usr/bin/link: missing operand after '\xff\xfe'

  This script imports VS Build Tools (vcvars64) and prioritizes MSVC link.exe.
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

function Import-MsvcBuildEnvironment {
    <#
      Load Visual Studio Build Tools env (INCLUDE/LIB/PATH) for MSVC linker.
    #>
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    $vcvars = $null

    if (Test-Path $vswhere) {
        $installPath = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null
        if ($installPath) {
            $candidate = Join-Path $installPath "VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path $candidate) { $vcvars = $candidate }
        }
    }

    if (-not $vcvars) {
        $fallbacks = @(
            "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
            "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
            "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
            "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
        )
        foreach ($f in $fallbacks) {
            if (Test-Path $f) { $vcvars = $f; break }
        }
    }

    if (-not $vcvars) {
        Write-Host "WARNING: VS Build Tools (vcvars64.bat) not found." -ForegroundColor Yellow
        Write-Host "  Install 'Desktop development with C++' or Build Tools, then retry."
        Write-Host "  https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        return $false
    }

    Write-Host "Importing MSVC env: $vcvars" -ForegroundColor DarkGray
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        # cmd exports env after vcvars; we import into this PowerShell process
        cmd.exe /c "`"$vcvars`" >nul 2>&1 && set" | Out-File -FilePath $tmp -Encoding ascii
        Get-Content $tmp | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                $name = $Matches[1]
                $value = $Matches[2]
                # Skip junk / pseudo vars
                if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
                    [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
                }
            }
        }
    }
    finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }

    # Explicit linker for cargo (immune to conda/Git ``link.exe`` shadowing)
    $msvcRoot = Join-Path (Split-Path (Split-Path (Split-Path $vcvars))) "Tools\MSVC"
    # vcvars path: ...\VC\Auxiliary\Build\vcvars64.bat → Tools\MSVC is sibling of Auxiliary
    $toolsMsvc = Join-Path (Split-Path (Split-Path $vcvars)) "Tools\MSVC"
    if (-not (Test-Path $toolsMsvc)) {
        $toolsMsvc = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"
    }
    $linkExe = $null
    if (Test-Path $toolsMsvc) {
        $hostLink = Get-ChildItem -Path $toolsMsvc -Recurse -Filter "link.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\Hostx64\\x64\\link\.exe$' } |
            Select-Object -First 1
        if ($hostLink) { $linkExe = $hostLink.FullName }
    }

    if ($linkExe) {
        $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = $linkExe
        # Prepend MSVC bin so rustc subprocesses also see the right link.exe
        $linkDir = Split-Path $linkExe
        $env:Path = "$linkDir;" + $env:Path
        Write-Host "  MSVC linker: $linkExe" -ForegroundColor DarkGray
        return $true
    }

    Write-Host "WARNING: MSVC link.exe not found under Build Tools." -ForegroundColor Yellow
    return $false
}

if ($IsWindows -or $env:OS -match 'Windows') {
    $ok = Import-MsvcBuildEnvironment
    if (-not $ok) {
        Write-Host "Continuing anyway; build may fail if link.exe is wrong." -ForegroundColor Yellow
    }
    else {
        # Sanity: first link.exe on PATH should be MSVC
        $firstLink = Get-Command link.exe -ErrorAction SilentlyContinue
        if ($firstLink) {
            Write-Host "  PATH link.exe → $($firstLink.Source)" -ForegroundColor DarkGray
            if ($firstLink.Source -notmatch 'MSVC|Visual Studio') {
                Write-Host "  WARNING: link.exe is not MSVC — conda/Git may still shadow it." -ForegroundColor Yellow
            }
        }
    }
}

# Tauri externalBin requires platform-suffixed sidecar (build fails if missing)
$triple = "x86_64-pc-windows-msvc"
try {
    $t = (& rustc --print host-tuple 2>$null | Out-String).Trim()
    if ($t) { $triple = $t }
} catch {}
$sidecar = Join-Path $Root "desktop\src-tauri\binaries\enpu-core-$triple.exe"
if (-not (Test-Path $sidecar)) {
    Write-Host "Sidecar missing: $sidecar" -ForegroundColor Yellow
    $prepare = Join-Path $PSScriptRoot "prepare-sidecar.ps1"
    $coreExe = Join-Path $Root "core\dist\enpu-core.exe"
    if (Test-Path $coreExe) {
        Write-Host "  Preparing from core\dist\enpu-core.exe ..." -ForegroundColor Yellow
        & $prepare -CoreExe $coreExe -SkipBuild
    }
    else {
        Write-Host "  core\dist\enpu-core.exe not found — building sidecar (slow)..." -ForegroundColor Yellow
        & $prepare
    }
    if (-not (Test-Path $sidecar)) {
        Write-Error "Could not create sidecar. Run: .\scripts\prepare-sidecar.ps1"
    }
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
