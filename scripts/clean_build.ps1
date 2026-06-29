# Deletes PyInstaller build/ and dist/ (local machine paths; do not commit these folders).

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

foreach ($d in @("build", "dist", "installer\output", "output", "PC Stat")) {
    $p = Join-Path (Get-Location) $d
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "Removed $d/"
    }
}
Write-Host "Done."
