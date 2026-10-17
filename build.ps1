# Build VoiceType.exe with PyInstaller (onedir mode: faster cold start than onefile)
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$vp = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $vp)) {
    Write-Host "venv not found. Run: python -m venv .venv" -ForegroundColor Red
    exit 1
}

Write-Host "[1/3] ensure pyinstaller" -ForegroundColor Cyan
& $vp -m pip install pyinstaller --index-url https://mirrors.cloud.tencent.com/pypi/simple --quiet

Write-Host "[2/3] clean previous build" -ForegroundColor Cyan
foreach ($d in @("build", "dist")) {
    $p = Join-Path $root $d
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Write-Host "[3/3] building" -ForegroundColor Cyan
& $vp -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name VoiceType `
    --paths $root `
    --hidden-import app `
    --add-data "$root\README.md;." `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtNetwork `
    --exclude-module tkinter `
    --exclude-module matplotlib `
    "$root\run.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "build failed" -ForegroundColor Red
    exit $LASTEXITCODE
}

$exe = Join-Path $root "dist\VoiceType\VoiceType.exe"
if (Test-Path $exe) {
    $size = [math]::Round((Get-ChildItem (Join-Path $root "dist\VoiceType") -Recurse -File |
        Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    Write-Host "OK -> $exe  (total $size MB)" -ForegroundColor Green
} else {
    Write-Host "exe not found" -ForegroundColor Red
    exit 1
}
