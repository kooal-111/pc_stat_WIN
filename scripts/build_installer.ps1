# Сборка PyInstaller onefile (dist\PCStat.exe), затем Inno Setup → installer\output\PCStat-Setup.exe
# Требуется Inno Setup 6: https://jrsoftware.org/isinfo.php

param(
    [switch]$NoQtCharts
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($NoQtCharts) {
    & (Join-Path $PSScriptRoot "build_windows.ps1") -OneFile -NoQtCharts
} else {
    & (Join-Path $PSScriptRoot "build_windows.ps1") -OneFile
}

$exe = Join-Path $root "dist\PCStat.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Error "Expected dist\PCStat.exe after onefile build."
}

$iscc = $null
foreach ($c in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )) {
    if (Test-Path -LiteralPath $c) {
        $iscc = $c
        break
    }
}
if (-not $iscc) {
    Write-Error "ISCC.exe not found. Install Inno Setup 6 and retry, or add ISCC to PATH."
}

$iss = Join-Path $root "installer\PCStat.iss"
$version = (& python (Join-Path $PSScriptRoot "generate_version_metadata.py") --print-version).Trim()
if (-not $version) {
    Write-Error "Could not read APP_VERSION from pc_stat_win\version.py."
}
Write-Host "Running Inno Setup for PC Stat $version"
& $iscc "/DMyAppVersion=$version" $iss
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$out = Join-Path $root "installer\output\PCStat-Setup.exe"
if (Test-Path -LiteralPath $out) {
    Write-Host ""
    Write-Host "Done: $out"
} else {
    Write-Warning "ISCC reported success but output not found at $out (check PCStat.iss OutputDir/BaseFilename)."
}
