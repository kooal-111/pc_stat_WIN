# Создаёт GitHub Release и прикрепляет один .exe (нужен GitHub CLI: gh).
# Установка: https://cli.github.com/
# Авторизация: gh auth login
#
# Пример (один файл PCStat.exe после build_windows.ps1 -OneFile):
#   .\scripts\publish_release.ps1 -Tag "v1.0.0" -Title "PC Stat 1.0.0"
#
# Пример (установщик после build_installer.ps1):
#   .\scripts\publish_release.ps1 -Tag "v1.0.0" -UseInstaller

param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [string]$Title = "",
    [switch]$UseInstaller,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Error "Не найден gh. Установите GitHub CLI (https://cli.github.com/) и выполните: gh auth login"
}

if ($UseInstaller) {
    $assetPath = Join-Path $root "installer\output\PCStat-Setup.exe"
} else {
    $assetPath = Join-Path $root "dist\PCStat.exe"
}

if (-not (Test-Path -LiteralPath $assetPath)) {
    Write-Error "Файл не найден: $assetPath. Соберите проект: build_windows.ps1 -OneFile или build_installer.ps1"
}

if (-not $Title) {
    $Title = "Release $Tag"
}

$relArgs = @(
    "release", "create", $Tag,
    $assetPath,
    "--title", $Title,
    "--latest"
)
if ($Notes) {
    $relArgs += "--notes"
    $relArgs += $Notes
} else {
    $relArgs += "--generate-notes"
}

Write-Host "gh $($relArgs -join ' ')"
& gh @relArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$releasesUrl = "https://github.com/kooal-111/pc_stat_WIN/releases"
try {
    $origin = git remote get-url origin 2>$null
    if ($origin -match "github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$") {
        $releasesUrl = "https://github.com/$($Matches[1])/$($Matches[2])/releases"
    }
} catch {}
Write-Host ""
Write-Host "Готово. Релизы: $releasesUrl"
