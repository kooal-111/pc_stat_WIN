# Устанавливает ТОЛЬКО для этого репозитория user.name и user.email (GitHub noreply),
# чтобы глобальный git config с личной почтой не попадал в коммиты.
# Запуск из корня репозитория:
#   .\scripts\setup_git_identity.ps1 -GitHubLogin "your_github_username"
# Либо сразу адрес из GitHub (Settings → Emails): -NoReplyEmail "id+login@users.noreply.github.com"

param(
    [string]$UserName = "PC Stat",
    [string]$GitHubLogin = "",
    [string]$NoReplyEmail = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path (Join-Path $root ".git"))) {
    Write-Error "Не найден .git. Запустите скрипт из клонированного репозитория."
}

if ($NoReplyEmail) {
    $email = $NoReplyEmail
} elseif ($GitHubLogin) {
    $u = Invoke-RestMethod -Uri "https://api.github.com/users/$GitHubLogin" -Headers @{ "User-Agent" = "pc_stat_WIN-setup" }
    $email = "$($u.id)+$GitHubLogin@users.noreply.github.com"
} else {
    Write-Error "Укажите -GitHubLogin `"<логин_GitHub>`" или полный -NoReplyEmail (см. комментарии в начале скрипта)."
}

git config --local user.name $UserName
git config --local user.email $email

Write-Host "Локально для этого репозитория:"
Write-Host "  user.name  = $UserName"
Write-Host "  user.email = $email"
Write-Host "Проверка: git config --local --list"
