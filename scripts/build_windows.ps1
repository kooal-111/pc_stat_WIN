# Portable build: dist\PCStat (Windows). Needs Python 3.10+ and project deps + PyInstaller.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

# onedir is more reliable for Qt than one-file .exe
python -m PyInstaller pc_stat_win.spec --noconfirm

Write-Host ""
Write-Host "Done: dist\PCStat\PCStat.exe"
Write-Host "Ship the whole folder dist\PCStat (or zip it)."
