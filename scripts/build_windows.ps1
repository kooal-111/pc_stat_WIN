# PyInstaller build. Default: onedir (dist\PCStat\). Use -OneFile for single dist\PCStat.exe

param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

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
