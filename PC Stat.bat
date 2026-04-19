@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pc_stat_win
  exit /b %ERRORLEVEL%
)

python -m pc_stat_win
if %ERRORLEVEL% equ 0 exit /b 0

py -3 -m pc_stat_win
if %ERRORLEVEL% equ 0 exit /b 0

echo.
echo [PC Stat] Python not found or dependencies missing.
echo Install Python 3.10+ from https://www.python.org/downloads/
echo Then in this folder:  pip install -r requirements.txt
echo.
pause
exit /b 1
