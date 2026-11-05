from pathlib import Path


# PyInstaller executes the spec in its own context, where __file__ is not guaranteed.
# Both build helper scripts invoke PyInstaller from the repository root, so use cwd.
ROOT = Path.cwd().resolve()
SOURCE_DIR = ROOT / "source_files"


a = Analysis(
    [str(SOURCE_DIR / 'pps_GUI_program.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(SOURCE_DIR / 'pps_GUI.ui'), '.'),
        (str(SOURCE_DIR / 'connection_dialog.ui'), '.'),
        (str(SOURCE_DIR / 'config.ini'), '.'),
        (str(SOURCE_DIR / 'device_dps5005.ini'), '.'),
        (str(SOURCE_DIR / 'device_xy-sk120.toml'), '.'),
        (str(SOURCE_DIR / 'icon'), 'icon'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='XYGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='XYGUI',
)
