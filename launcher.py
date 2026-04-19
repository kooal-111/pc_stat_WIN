"""Точка входа для сборки PyInstaller (один .exe + папка или один файл)."""
from __future__ import annotations

from pc_stat_win.main import main

if __name__ == "__main__":
    raise SystemExit(main())
