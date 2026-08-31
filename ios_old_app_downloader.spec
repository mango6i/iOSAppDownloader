# -*- mode: python ; coding: utf-8 -*-
hiddenimports = ['PyQt6.sip']
version_file = 'version_info.txt'


a = Analysis(
    ['ios_old_app_downloader.py'],
    pathex=[],
    binaries=[
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/ipatool/kosthi/ipatool.exe', '.'),
        ('C:/Windows/System32/icuuc.dll', '.'),
    ],
    datas=[
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/appstore.ico', '.'),
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/ipatool/engine_seed', 'engine_seed'),
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/ipatool/kosthi/LICENSE', 'licenses/ipatool-rs'),
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/ipatool/kosthi/README.md', 'licenses/ipatool-rs'),
        ('C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/ipatool/kosthi/CHANGELOG.md', 'licenses/ipatool-rs'),
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
    icon='C:/Users/Administrator/WorkBuddy/2026-08-29-11-52-41/appstore.ico',
    version=version_file,
)
