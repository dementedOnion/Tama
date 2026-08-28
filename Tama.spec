# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import PySide6


pyside_dir = Path(PySide6.__file__).parent
vc_runtime_binaries = [
    (str(pyside_dir / "VCRUNTIME140.dll"), "."),
    (str(pyside_dir / "VCRUNTIME140_1.dll"), "."),
]


a = Analysis(
    ["src/main.py"],
    pathex=[],
    binaries=vc_runtime_binaries,
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# The Codex host exposes document-tool DLLs (Poppler/libheif) to child
# processes. They are unrelated to Tama and can collide with Qt's DLL names.
a.binaries = type(a.binaries)(
    entry for entry in a.binaries if "\\.cache\\codex-runtimes\\" not in entry[1].lower()
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Tama",
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
