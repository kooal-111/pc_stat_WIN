PC Stat - готовый PCStat.exe не хранится в репозитории.

Скачайте portable-файлы из последнего GitHub Release:
  https://github.com/kooal-111/pc_stat_WIN/releases/latest

Нужны два файла:
  PCStat.exe
  SHA256SUMS.txt

Проверка SHA-256 в PowerShell:
  (Get-FileHash .\PCStat.exe -Algorithm SHA256).Hash

Полученное значение должно совпасть с SHA256SUMS.txt. После проверки
запустите PCStat.exe двойным щелчком.

Для локальной сборки из исходников:
  .\scripts\build_windows.ps1 -OneFile

Результат локальной сборки находится в dist\PCStat.exe.
