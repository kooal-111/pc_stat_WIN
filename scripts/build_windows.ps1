# PyInstaller build. Default: onedir (dist\PCStat\). Use -OneFile for single dist\PCStat.exe

param(
    [switch]$OneFile,
    [switch]$NoQtCharts
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install -r requirements.txt -r requirements-build.txt

python -c "from pc_stat_win.branding import write_packaged_icon_assets; p=write_packaged_icon_assets(); print('Icons:', p[0], p[1])"
python scripts\generate_version_metadata.py

if ($NoQtCharts) {
    $env:PCSTAT_WITH_QTCHARTS = "0"
} else {
    $env:PCSTAT_WITH_QTCHARTS = "1"
}

if ($OneFile) {
    python -m PyInstaller pc_stat_win_onefile.spec --noconfirm
    Write-Host ""
    Write-Host "Done: dist\PCStat.exe (single file)"
} else {
    python -m PyInstaller pc_stat_win.spec --noconfirm
    Write-Host ""
    Write-Host "Done: dist\PCStat\PCStat.exe (folder build)"
}

Write-Host "Do not commit build/ or dist/."
