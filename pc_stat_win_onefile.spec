# -*- mode: python ; coding: utf-8 -*-
# Single-file exe: pyinstaller pc_stat_win_onefile.spec
# Output: dist/PCStat.exe (one file; slower cold start than onedir)

from pathlib import Path

try:
    _ROOT = Path(SPECPATH).resolve()
except NameError:
    _ROOT = Path(__file__).resolve().parent

_datas = [
    (str(_ROOT / "pc_stat_win" / "ui" / "theme_dark.qss"), "pc_stat_win/ui"),
    (str(_ROOT / "pc_stat_win" / "ui" / "theme_light.qss"), "pc_stat_win/ui"),
]

block_cipher = None

a = Analysis(
    [str(_ROOT / "launcher.py")],
    pathex=[str(_ROOT)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "win32timezone",
        "win32api",
        "win32gui",
        "win32process",
        "PySide6.QtCharts",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PCStat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
