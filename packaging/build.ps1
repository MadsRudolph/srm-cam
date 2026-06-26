<#
.SYNOPSIS
    Build SRM-CAM into a Windows installer (Setup.exe).

.DESCRIPTION
    Two stages:
      1. PyInstaller  -> dist\SRM-CAM\         (the runnable app folder)
      2. Inno Setup   -> dist_installer\*.exe  (the downloadable installer)

    Run from anywhere; paths are resolved relative to this script.

.PARAMETER BasePython
    Interpreter used to CREATE the isolated build venv (only its stdlib + venv
    module are used). Defaults to the standalone CPython 3.13. Deliberately NOT
    the miniconda base — building from that fat env bundles torch/scipy/pygame
    and bloats the installer to multiple GB.

.PARAMETER Recreate
    Delete and rebuild the build venv from scratch (use after changing deps).

.PARAMETER SkipInstaller
    Build only the PyInstaller app folder; skip the Inno Setup step.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param(
    [string]$BasePython = "C:\Users\Mads2\AppData\Local\Programs\Python\Python313\python.exe",
    [switch]$Recreate,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot          # repo root (packaging\ -> ..)
Set-Location $Root
$VenvDir = Join-Path $Root ".build-venv"
$Python  = Join-Path $VenvDir "Scripts\python.exe"
Write-Host "== SRM-CAM build ==" -ForegroundColor Cyan
Write-Host "repo root : $Root"

# --- isolated build venv (only the app's runtime deps + pyinstaller) -------
if ($Recreate -and (Test-Path $VenvDir)) {
    Write-Host "Removing existing build venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $Python)) {
    if (-not (Test-Path $BasePython)) { throw "Base Python not found: $BasePython" }
    Write-Host "Creating build venv at $VenvDir ..." -ForegroundColor Yellow
    & $BasePython -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r "packaging\requirements-build.txt"
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
}
Write-Host "python    : $Python"

# --- stage 1: PyInstaller -------------------------------------------------
Write-Host "`n[1/2] PyInstaller..." -ForegroundColor Cyan
& $Python -m PyInstaller --noconfirm "packaging\srm-cam.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
$AppExe = Join-Path $Root "dist\SRM-CAM\SRM-CAM.exe"
if (-not (Test-Path $AppExe)) { throw "Expected app missing: $AppExe" }
Write-Host "  -> $AppExe" -ForegroundColor Green

if ($SkipInstaller) { Write-Host "`nDone (app folder only)."; exit 0 }

# --- stage 2: Inno Setup --------------------------------------------------
Write-Host "`n[2/2] Inno Setup..." -ForegroundColor Cyan
$Iscc = $null
$cmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($cmd) { $Iscc = $cmd.Source }
foreach ($p in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (-not $Iscc -and (Test-Path $p)) { $Iscc = $p }
}
if (-not $Iscc) {
    Write-Warning "Inno Setup (ISCC.exe) not found. The app folder is built at dist\SRM-CAM\."
    Write-Warning "Install it with:  winget install --id JRSoftware.InnoSetup -e"
    Write-Warning "then re-run this script to produce Setup.exe."
    exit 2
}
Write-Host "iscc      : $Iscc"
& $Iscc "packaging\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }

$Setup = Get-ChildItem "dist_installer\SRM-CAM-Setup-*.exe" -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime | Select-Object -Last 1
if ($Setup) { Write-Host "`nDone -> $($Setup.FullName)" -ForegroundColor Green }
else { Write-Host "`nDone (installer step ran; check dist_installer\)." }
