# Validates and publishes the attested CI one-file artifact for the exact HEAD.

param(
    [string]$Title = "",
    [string]$Notes = "",
    [string]$Repo = "",
    [string]$Remote = "origin"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location $root

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function Get-CheckedOutput([string]$Command, [string[]]$Arguments) {
    $output = & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
    return ($output | Out-String).Trim()
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found."
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) was not found. Install it and run: gh auth login -h github.com"
}

$gitRoot = Get-CheckedOutput "git" @("rev-parse", "--show-toplevel")
if ([System.IO.Path]::GetFullPath($gitRoot) -ne $root) {
    throw "Run this script from a Git checkout whose root is $root."
}
$status = Get-CheckedOutput "git" @("status", "--porcelain", "--untracked-files=normal")
if ($status) {
    throw "The Git checkout must be clean before publishing.`n$status"
}
Invoke-Checked "gh" @("auth", "status", "--hostname", "github.com")

if (-not $Repo) {
    $Repo = Get-CheckedOutput "gh" @("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
}
if ($Repo -notmatch "^[^/]+/[^/]+$") {
    throw "Could not determine an owner/name GitHub repository. Pass -Repo owner/name."
}

$version = Get-CheckedOutput "python" @((Join-Path $PSScriptRoot "generate_version_metadata.py"), "--print-version")
if ($version -ne "1.3.0") {
    throw "This release script expects APP_VERSION 1.3.0, got $version."
}
$tag = "v$version"
$headSha = Get-CheckedOutput "git" @("rev-parse", "HEAD")

Write-Host "Running release gates for $tag at $headSha"
Invoke-Checked "python" @("-m", "unittest", "discover", "-s", "tests")
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    Invoke-Checked "python" @("scripts\smoke_ui_qt.py")
} finally {
    $env:QT_QPA_PLATFORM = $oldPlatform
}

$remoteMain = Get-CheckedOutput "git" @("ls-remote", "--exit-code", "--heads", $Remote, "refs/heads/main")
$remoteMainSha = ($remoteMain -split "\s+")[0]
if ($remoteMainSha -ne $headSha) {
    throw "origin/main is $remoteMainSha instead of exact HEAD $headSha. Push the reviewed commit first."
}

$workflowRun = $null
for ($attempt = 0; $attempt -lt 12 -and $null -eq $workflowRun; $attempt++) {
    $runsJson = Get-CheckedOutput "gh" @(
        "run", "list", "--repo", $Repo,
        "--workflow", "Windows CI", "--commit", $headSha,
        "--event", "push", "--limit", "10",
        "--json", "databaseId,status,conclusion,headSha"
    )
    $workflowRun = @($runsJson | ConvertFrom-Json) |
        Sort-Object databaseId -Descending |
        Select-Object -First 1
    if ($null -eq $workflowRun) {
        Start-Sleep -Seconds 5
    }
}
if ($null -eq $workflowRun) {
    throw "No Windows CI push run was found for exact commit $headSha."
}
if ($workflowRun.status -ne "completed") {
    Invoke-Checked "gh" @(
        "run", "watch", [string]$workflowRun.databaseId,
        "--repo", $Repo, "--exit-status"
    )
} elseif ($workflowRun.conclusion -ne "success") {
    throw "Windows CI run $($workflowRun.databaseId) concluded with '$($workflowRun.conclusion)'."
}

$stagingBase = [System.IO.Path]::GetFullPath((Join-Path $root "output\release-staging"))
$expectedStagingPrefix = [System.IO.Path]::GetFullPath((Join-Path $root "output")) + [System.IO.Path]::DirectorySeparatorChar
if (-not $stagingBase.StartsWith($expectedStagingPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Release staging directory escaped the repository output directory."
}
$releaseRoot = Join-Path $stagingBase ([guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $releaseRoot | Out-Null
try {
    $artifactName = "PCStat-$version-windows-x64"
    Invoke-Checked "gh" @(
        "run", "download", [string]$workflowRun.databaseId,
        "--repo", $Repo, "--name", $artifactName, "--dir", $releaseRoot
    )
    $assetPath = Join-Path $releaseRoot "PCStat.exe"
    $checksumPath = Join-Path $releaseRoot "SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
        throw "Verified CI artifact did not contain PCStat.exe."
    }
    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
        throw "Verified CI artifact did not contain SHA256SUMS.txt."
    }

    $hash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumLine = (Get-Content -LiteralPath $checksumPath -Raw).Trim()
    if ($checksumLine -ne "$hash  PCStat.exe") {
        throw "CI checksum does not match the downloaded PCStat.exe."
    }
    Invoke-Checked "gh" @("attestation", "verify", $assetPath, "--repo", $Repo)

    $versionInfo = (Get-Item -LiteralPath $assetPath).VersionInfo
    if ($versionInfo.FileVersion -ne $version) {
        throw "Embedded FileVersion is '$($versionInfo.FileVersion)', expected '$version'."
    }
    if ($versionInfo.ProductVersion -ne $version) {
        throw "Embedded ProductVersion is '$($versionInfo.ProductVersion)', expected '$version'."
    }

    $expectedSchemaVersion = "7"
    $smokeDir = Join-Path $releaseRoot "smoke"
    $smokeDb = Join-Path $smokeDir "data.sqlite"
    New-Item -ItemType Directory -Path $smokeDir | Out-Null
    $oldDbPath = $env:PCSTAT_DB_PATH
    $oldPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:PCSTAT_DB_PATH = $smokeDb
        $env:QT_QPA_PLATFORM = "offscreen"
        $process = Start-Process -FilePath $assetPath -ArgumentList "--smoke-test" -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Packaged smoke failed with exit code $($process.ExitCode)."
        }
        if (-not (Test-Path -LiteralPath $smokeDb -PathType Leaf)) {
            throw "Packaged smoke did not create the redirected SQLite database."
        }

        $dbCheck = Get-CheckedOutput "python" @(
            "-c",
            "import sqlite3,sys;db=sqlite3.connect(sys.argv[1]);schema=db.execute(sys.argv[2]).fetchone();quick=db.execute(sys.argv[3]).fetchone();db.close();print((schema or [chr(0)])[0]+chr(124)+(quick or [chr(0)])[0])",
            $smokeDb,
            "SELECT value FROM meta WHERE key='schema_version'",
            "PRAGMA quick_check"
        )
        if ($dbCheck -ne "$expectedSchemaVersion|ok") {
            throw "Packaged SQLite validation failed: expected $expectedSchemaVersion|ok, got $dbCheck."
        }
    } finally {
        $env:PCSTAT_DB_PATH = $oldDbPath
        $env:QT_QPA_PLATFORM = $oldPlatform
        if (Test-Path -LiteralPath $smokeDir) {
            Remove-Item -LiteralPath $smokeDir -Recurse -Force
        }
    }

    $postBuildStatus = Get-CheckedOutput "git" @("status", "--porcelain", "--untracked-files=normal")
    if ($postBuildStatus) {
        throw "Release gates changed the Git checkout; refusing to tag or publish.`n$postBuildStatus"
    }

    & git show-ref --verify --quiet "refs/tags/$tag"
    $tagLookupExitCode = $LASTEXITCODE
    if ($tagLookupExitCode -notin 0, 1) {
        throw "Unable to determine whether local tag $tag exists."
    }
    $tagExists = $tagLookupExitCode -eq 0
    if ($tagExists) {
        $tagType = Get-CheckedOutput "git" @("cat-file", "-t", $tag)
        if (($tagType | Out-String).Trim() -ne "tag") {
            throw "$tag exists locally but is not an annotated tag."
        }
        $tagCommit = Get-CheckedOutput "git" @("rev-list", "-n", "1", $tag)
        if ($tagCommit -ne $headSha) {
            throw "$tag points to $tagCommit instead of exact HEAD $headSha."
        }
    } else {
        Invoke-Checked "git" @("tag", "-a", $tag, $headSha, "-m", "PC Stat $version")
    }

    Invoke-Checked "git" @("push", $Remote, "refs/tags/${tag}:refs/tags/${tag}")
    $remoteTag = Get-CheckedOutput "git" @("ls-remote", "--exit-code", "--tags", $Remote, "refs/tags/$tag^{}")
    $remoteCommit = ($remoteTag -split "\s+")[0]
    if ($remoteCommit -ne $headSha) {
        throw "Remote annotated tag $tag resolves to $remoteCommit instead of $headSha."
    }

    if (-not $Title) {
        $Title = "PC Stat $version"
    }
    $releaseArgs = @(
        "release", "create", $tag,
        $assetPath,
        $checksumPath,
        "--repo", $Repo,
        "--verify-tag",
        "--target", $headSha,
        "--title", $Title,
        "--latest"
    )
    if ($Notes) {
        $releaseArgs += @("--notes", $Notes)
    } else {
        $releaseArgs += "--generate-notes"
    }

    Write-Host "Publishing $tag for $Repo at $headSha"
    Invoke-Checked "gh" $releaseArgs
    Write-Host "Published verified CI artifact $tag ($hash)"
} finally {
    if (Test-Path -LiteralPath $releaseRoot) {
        Remove-Item -LiteralPath $releaseRoot -Recurse -Force
    }
}
