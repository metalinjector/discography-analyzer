# -*- mode: python ; coding: utf-8 -*-
"""Build: python -m PyInstaller --clean --noconfirm --upx-dir tools/upx/upx-4.2.4-win64 build_exe.spec

One-file portable .exe for the Discography Analyzer (tkinter GUI, no console).
tkinter is the GUI framework here and MUST NOT be excluded (unlike Qt specs).
"""
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # mutagen.File is a dynamic format factory - bundle every handler.
    hiddenimports=(
        collect_submodules('mutagen')
        + collect_submodules('discography_analyzer')
        + collect_submodules('openpyxl')
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'scipy', 'pandas', 'matplotlib', 'cv2',
        'jupyter', 'IPython', 'setuptools', 'pip', 'test', 'unittest',
        'PySide6', 'PyQt5', 'PyQt6',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='Discography_Analyzer_1.15.0',
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