# Публикация на GitHub: анонимность и раздача .exe

## Локальная личность в git (без личной почты в коммитах)

Глобальный `git config` может содержать вашу настоящую почту. Для этого репозитория задайте **только локально** имя и GitHub **noreply**-адрес:

```powershell
.\scripts\setup_git_identity.ps1
```

По умолчанию используется логин `kooal-111` и публичный API GitHub для формата `{id}+{login}@users.noreply.github.com`. Свой логин:

```powershell
.\scripts\setup_git_identity.ps1 -GitHubLogin "ВАШ_ЛОГИН" -UserName "Псевдоним"
```

Или вставьте адрес вручную из GitHub → **Settings → Emails** (блок про noreply):

```powershell
.\scripts\setup_git_identity.ps1 -NoReplyEmail "12345+username@users.noreply.github.com" -UserName "Псевдоним"
```

## Что не коммитить

- `build/`, `dist/`, `installer/output/` — в `.gitignore` (в сборках бывают абсолютные пути с вашего ПК).
- Токены, пароли, личные базы SQLite, скриншоты с полным путём `C:\Users\...`.

Перед `git add` полезно: `git status` и просмотр `git diff`.

## Первый push и обновления

```powershell
git add -A
git status   # убедитесь, что нет лишнего
git commit -m "Описание изменений"
git push origin main
```

Если репозиторий на GitHub уже создан, `origin` должен указывать на него (`git remote -v`).

## Сборка файла для пользователей

**Один exe (проще всего раздать файл):**

```powershell
.\scripts\build_windows.ps1 -OneFile
```

Результат: `dist\PCStat.exe`.

**Локальный установщик (альтернатива):** нужен [Inno Setup 6](https://jrsoftware.org/isinfo.php), затем:

```powershell
.\scripts\build_installer.ps1
```

Результат: `installer\output\PCStat-Setup.exe`.

Готовый `PCStat.exe` не коммитится в `download/`: portable-сборка публикуется как GitHub Release asset. Каталоги `build/`, `dist/` и файл `download/PCStat.exe` находятся в `.gitignore`.

## GitHub Releases

Релиз содержит portable `PCStat.exe` и `SHA256SUMS.txt`. EXE собирается в Windows CI и получает
GitHub/Sigstore provenance attestation.

1. Отправьте проверенный commit в `origin/main` и дождитесь запуска Windows CI.
2. Установите [GitHub CLI](https://cli.github.com/) и выполните `gh auth login`.
3. Создайте релиз:

```powershell
.\scripts\publish_release.ps1
```

Скрипт читает `APP_VERSION` из `pc_stat_win/version.py`, находит CI для точного `HEAD`, ждёт его
завершения, скачивает артефакт, проверяет checksum и `gh attestation verify`, затем формирует тег
`v<APP_VERSION>` и публикует оба проверенных portable-файла.

Ручная загрузка локально собранного EXE не рекомендуется: она обходит provenance-проверку.

Ссылка «последняя версия»:

`https://github.com/kooal-111/pc_stat_WIN/releases/latest`

## SmartScreen

Неподписанный exe может вызвать предупреждение Windows — это ожидаемо для самодельных сборок.
