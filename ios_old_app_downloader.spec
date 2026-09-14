# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import re

# PyInstaller executes a spec in a namespace where __file__ is not guaranteed.
# SPECPATH is provided by PyInstaller and keeps the build portable.
ROOT = Path(SPECPATH) if 'SPECPATH' in globals() else Path.cwd()
WINDOWS_DIR = Path(os.environ.get('WINDIR', 'C:/Windows'))
hiddenimports = ['PyQt6.sip']

# Keep one version source of truth.  The application version controls the EXE
# name and Windows metadata, so future releases do not require three separate
# manual edits.
source_text = (ROOT / 'ios_old_app_downloader.py').read_text(encoding='utf-8')
version_match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', source_text, re.MULTILINE)
if not version_match:
    raise RuntimeError('APP_VERSION was not found in ios_old_app_downloader.py')
APP_VERSION = version_match.group(1)
try:
    version_parts = [int(part) for part in APP_VERSION.split('.')]
except ValueError as exc:
    raise RuntimeError('APP_VERSION must contain numeric dot-separated parts') from exc
VERSION_TUPLE = tuple((version_parts + [0, 0, 0, 0])[:4])
FILE_VERSION = '.'.join(str(part) for part in VERSION_TUPLE)

generated_dir = ROOT / 'build' / '_generated'
generated_dir.mkdir(parents=True, exist_ok=True)
version_file = generated_dir / 'version_info.txt'
version_file.write_text(f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={VERSION_TUPLE},
    prodvers={VERSION_TUPLE},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [StringTable(
        '080404B0',
        [StringStruct('CompanyName', '果果'),
         StringStruct('FileDescription', 'iOS 旧版应用下载工具'),
         StringStruct('FileVersion', '{FILE_VERSION}'),
         StringStruct('InternalName', 'iOSAppDownloader'),
         StringStruct('LegalCopyright', 'Copyright (C) 2026 果果'),
         StringStruct('OriginalFilename', 'iOSAppDownloader_v{APP_VERSION}.exe'),
         StringStruct('ProductName', 'iOS App Downloader'),
         StringStruct('ProductVersion', '{FILE_VERSION}')]
      )]
    ),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
''', encoding='utf-8')

datas = [
    (str(ROOT / 'appstore.ico'), '.'),
    (str(ROOT / 'ipatool' / 'kosthi' / 'LICENSE'), 'licenses/ipatool-rs'),
    (str(ROOT / 'ipatool' / 'kosthi' / 'README.md'), 'licenses/ipatool-rs'),
    (str(ROOT / 'ipatool' / 'kosthi' / 'CHANGELOG.md'), 'licenses/ipatool-rs'),
]
engine_seed = ROOT / 'ipatool' / 'engine_seed'
if engine_seed.is_dir():
    datas.append((str(engine_seed), 'engine_seed'))


a = Analysis(
    [str(ROOT / 'ios_old_app_downloader.py')],
    pathex=[str(ROOT)],
    binaries=[
        # Qt6Core dynamically imports the Windows ICU shim on this target.
        # Keep it in the PyInstaller root for Qt, while ipatool remains isolated.
        (str(WINDOWS_DIR / 'System32' / 'icuuc.dll'), '.'),
        # Do not place ipatool beside the bundled Python/Qt DLLs. Keeping the
        # Rust executable isolated prevents Windows DLL lookup collisions.
        (str(ROOT / 'ipatool' / 'kosthi' / 'ipatool.exe'), 'ipatool/kosthi'),
    ],
    datas=datas,
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
    name=f'iOSAppDownloader_v{APP_VERSION}',
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
    version=str(version_file),
)
