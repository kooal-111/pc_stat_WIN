# Копирует dist\PCStat.exe в download\PCStat.exe после сборки onefile.
# Запуск из корня: .\scripts\sync_download_exe.ps1

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$src = Join-Path $root "dist\PCStat.exe"
$dstDir = Join-Path $root "download"
$dst = Join-Path $dstDir "PCStat.exe"

if (-not (Test-Path -LiteralPath $src)) {
    Write-Error "Нет $src. Сначала: .\scripts\build_windows.ps1 -OneFile"
}
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item -LiteralPath $src -Destination $dst -Force
Write-Host "Обновлено: $dst"
