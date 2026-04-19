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

**Установщик (рекомендуется пользователям):** нужен [Inno Setup 6](https://jrsoftware.org/isinfo.php), затем:

```powershell
.\scripts\build_installer.ps1
```

Результат: `installer\output\PCStat-Setup.exe`.

**Копия для пользователей в репозитории:** после onefile-сборки выполните `.\scripts\sync_download_exe.ps1` — в папку **`download/`** попадёт актуальный `PCStat.exe`, его и коммитят (см. README). Каталоги **`build/`** и **`dist/`** по-прежнему в `.gitignore`.

## GitHub Releases (по желанию)

Дополнительно к папке `download/` можно выкладывать тот же файл как вложение релиза.

1. Соберите `dist\PCStat.exe` или `installer\output\PCStat-Setup.exe`.
2. Установите [GitHub CLI](https://cli.github.com/) и выполните `gh auth login`.
3. Создайте релиз:

```powershell
.\scripts\publish_release.ps1 -Tag "v1.0.0" -Title "PC Stat 1.0.0"
```

Для установщика добавьте `-UseInstaller`.

**Вручную:** на сайте GitHub → репозиторий → **Releases** → **Draft a new release** → тег `v1.0.0` → прикрепите файл в **Attach binaries** → **Publish release**.

Ссылка «последняя версия»:

`https://github.com/kooal-111/pc_stat_WIN/releases/latest`

## SmartScreen

Неподписанный exe может вызвать предупреждение Windows — это ожидаемо для самодельных сборок.
