# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SRM-CAM (gerber2rml GUI).

Build (from the repo root, with the miniconda env that has the GUI deps):
    python -m PyInstaller --noconfirm packaging/srm-cam.spec

Produces a one-folder app at dist/SRM-CAM/ (SRM-CAM.exe + _internal/).
The Inno Setup script (packaging/installer.iss) wraps that folder into Setup.exe.

One-folder (not one-file) is deliberate: faster cold start (no temp unpack of a
~400 MB archive every launch) and the installer bundles the folder anyway.
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent                       # repo root (spec lives in packaging/)
DEMO = ROOT / "examples" / "preload_example"

# ---- data files ----------------------------------------------------------
datas = []
datas += collect_data_files("pyqtgraph")           # icons, shaders, colormaps
datas += collect_data_files("gerbonara")           # any packaged resources
# the preload demo board, so a fresh install opens with something on screen
if DEMO.is_dir():
    for f in DEMO.iterdir():
        if f.is_file():
            datas.append((str(f), "examples/preload_example"))

# ---- modules imported dynamically (not seen by static analysis) ----------
hiddenimports = []
hiddenimports += collect_submodules("gerber2rml")  # backends/engine registries
hiddenimports += collect_submodules("pyqtgraph")
hiddenimports += collect_submodules("OpenGL")      # PyOpenGL platform/back ends
hiddenimports += collect_submodules("gerbonara")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep the bundle lean and free of a second Qt binding (the PyQt5/6 clash
    # that crashed the 3D views) and test-only / unused stacks.
    excludes=[
        "PyQt5", "PyQt6",            # the second-Qt-binding clash
        "tkinter", "pytest", "_pytest", "IPython",
        # heavyweights the app never uses — guard against a fat env leaking in
        "torch", "scipy", "pygame", "tensorboard", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SRM-CAM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # windowed GUI; flip to True to see tracebacks
    disable_windowed_traceback=False,
    icon=None,                     # TODO: add packaging/srm-cam.ico when we have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SRM-CAM",
)
