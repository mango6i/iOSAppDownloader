# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

# PyInstaller executes a spec in a namespace where __file__ is not guaranteed.
# SPECPATH is provided by PyInstaller and keeps the build portable.
ROOT = Path(SPECPATH) if 'SPECPATH' in globals() else Path.cwd()
WINDOWS_DIR = Path(os.environ.get('WINDIR', 'C:/Windows'))
hiddenimports = ['PyQt6.sip', 'winpty', 'winpty.ptyprocess', 'winpty._winpty',
                 'unicorn', 'unicorn.unicorn', 'unicorn.unicorn_py3']
version_file = str(ROOT / 'version_info.txt')

# unicorn 是 C 扩展包，其原生库（unicorn/lib/unicorn.dll）不会被自动收集。
# 缺失时运行期会报 "Failed to load the Unicorn dynamic library"，
# 进而导致 SAP 运行时不可用，因此必须显式收集。
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files
    unicorn_binaries = collect_dynamic_libs('unicorn')
    unicorn_datas = collect_data_files('unicorn', include_py_files=False)
except Exception:
    unicorn_binaries = []
    unicorn_datas = []


a = Analysis(
    [str(ROOT / 'ios_old_app_downloader.py')],
    pathex=[str(ROOT)],
    binaries=[
        (str(WINDOWS_DIR / 'System32' / 'icuuc.dll'), '.'),
    ] + unicorn_binaries,
    datas=[
        (str(ROOT / 'appstore.ico'), '.'),
        (str(ROOT / 'ipatool' / 'engine_seed'), 'engine_seed'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'LICENSE'), 'licenses/ipatool-rs'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'README.md'), 'licenses/ipatool-rs'),
        (str(ROOT / 'ipatool' / 'kosthi' / 'CHANGELOG.md'), 'licenses/ipatool-rs'),
    ] + unicorn_datas,
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
    name='iOSAppDownloader_v1.0.7',
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
