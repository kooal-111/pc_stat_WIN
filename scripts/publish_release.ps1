# Publishes the portable one-file executable and its SHA-256 checksum.

param(
    [string]$Title = "",
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) was not found. Install it and run: gh auth login"
}

$version = (& python (Join-Path $PSScriptRoot "generate_version_metadata.py") --print-version).Trim()
if (-not $version) {
    Write-Error "Could not read APP_VERSION from pc_stat_win\version.py."
}
$tag = "v$version"
$assetPath = Join-Path $root "dist\PCStat.exe"
$checksumPath = Join-Path $root "dist\SHA256SUMS.txt"

if (-not (Test-Path -LiteralPath $assetPath)) {
    Write-Error "Missing dist\PCStat.exe. Run: .\scripts\build_windows.ps1 -OneFile"
}

$hash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  PCStat.exe" -Encoding ascii

if (-not $Title) {
    $Title = "PC Stat $version"
}

$releaseArgs = @(
    "release", "create", $tag,
    $assetPath,
    $checksumPath,
    "--title", $Title,
    "--latest"
)
if ($Notes) {
    $releaseArgs += @("--notes", $Notes)
} else {
    $releaseArgs += "--generate-notes"
}

Write-Host "Publishing $tag with PCStat.exe and SHA256SUMS.txt"
& gh @releaseArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Published $tag"
