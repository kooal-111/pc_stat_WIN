# PyInstaller build. Default: onedir (dist\PCStat\). Use -OneFile for dist\PCStat.exe.

param(
    [switch]$OneFile,
    [switch]$NoQtCharts
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$rootPrefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
Set-Location $root

function Get-RepoTarget([string]$RelativePath) {
    $target = [System.IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    if (-not $target.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to use a path outside the repository: $target"
    }
    return $target
}

function Remove-RepoTarget([string]$RelativePath) {
    $target = Get-RepoTarget $RelativePath
    if (Test-Path -LiteralPath $target) {
        Write-Host "Removing stale build target: $target"
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

python -c "import sys; assert sys.version_info[:2] == (3, 11), 'PC Stat builds require Python 3.11'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pip install --require-hashes -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Both distribution forms are removed so an old onefile executable can never be
# mistaken for the result of a later onedir build. Tracked icon assets are inputs.
Remove-RepoTarget "dist\PCStat.exe"
Remove-RepoTarget "dist\PCStat"
Remove-RepoTarget "dist\SHA256SUMS.txt"
Remove-RepoTarget "build\pc_stat_win"
Remove-RepoTarget "build\pc_stat_win_onefile"

python scripts\generate_version_metadata.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($NoQtCharts) {
    $env:PCSTAT_WITH_QTCHARTS = "0"
} else {
    $env:PCSTAT_WITH_QTCHARTS = "1"
}

$distPath = Get-RepoTarget "dist"
$workPath = Get-RepoTarget "build"
if ($OneFile) {
    python -m PyInstaller pc_stat_win_onefile.spec --clean --noconfirm --distpath $distPath --workpath $workPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
    Write-Host "Done: dist\PCStat.exe (single file)"
} else {
    python -m PyInstaller pc_stat_win.spec --clean --noconfirm --distpath $distPath --workpath $workPath
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host ""
    Write-Host "Done: dist\PCStat\PCStat.exe (folder build)"
}

Write-Host "Do not commit build/ or dist/."
