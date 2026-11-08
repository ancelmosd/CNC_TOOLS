# -*- mode: python ; coding: utf-8 -*-
"""
GCodeTools.spec — Empacotamento do GCode Tools com PyInstaller.

Uso:
    pyinstaller --noconfirm --clean GCodeTools.spec

O resultado fica em dist/GCodeTools/GCodeTools.exe (modo onedir).
O modo onedir é recomendado para PySide6 + PyVista/VTK: inicia mais rápido
e evita problemas de extração de DLLs do modo onefile.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# PyVista/VTK carregam muitos módulos e plugins de forma dinâmica.
# collect_all garante que módulos, dados e DLLs sejam incluídos.
for package in ("pyvista", "pyvistaqt", "vtk", "vtkmodules", "qtpy"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Módulos internos do projeto (garante que todas as abas sejam incluídas).
hiddenimports += collect_submodules("core")
hiddenimports += collect_submodules("gui")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "pytest",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GCodeTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="GCodeTools",
)
