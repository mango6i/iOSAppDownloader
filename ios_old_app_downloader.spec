# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

# PyInstaller executes a spec in a namespace where __file__ is not guaranteed.
# SPECPATH is provided by PyInstaller and keeps the build portable.
ROOT = Path(SPECPATH) if 'SPECPATH' in globals() else Path.cwd()
WINDOWS_DIR = Path(os.environ.get('WINDIR', 'C:/Windows'))
hiddenimports = ['PyQt6.sip']
version_file = str(ROOT / 'version_info.txt')


a = Analysis(
    [str(ROOT / 'ios_old_app_downloader.py')],
    pathex=[str(ROOT)],
    binaries=[
        (str(ROOT / 'ipatool' / 'kosthi' / 'ipatool.exe'), '.'),
        (str(WINDOWS_DIR / 'System32' / 'icuuc.dll'), '.'),
    ],
    datas=[
        (str(ROOT / 'appstore.ico'), '.'),
        (str(ROOT / 'ipatool' / 'engine_seed'), 'engine_seed'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'LICENSE'), 'licenses/ipatool-rs'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'README.md'), 'licenses/ipatool-rs'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'CHANGELOG.md'), 'licenses/ipatool-rs'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6.QtNetworkAuth', 'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D',
              'PyQt6.QtQuickWidgets', 'PyQt6.Qt3DCore', 'PyQt6.QtDesigner', 'PyQt6.QtHelp',
              'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineQuick',
              'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
              'numpy', 'tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython'],
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if entry[0].lower() != 'icudt78.dll']
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='iOSAppDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'appstore.ico'),
    version=version_file,
)
