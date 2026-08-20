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
KICAD_PLUGIN = ROOT / "kicad-plugin"

# ---- data files ----------------------------------------------------------
datas = []
datas += collect_data_files("pyqtgraph")           # icons, shaders, colormaps
datas += collect_data_files("gerbonara")           # any packaged resources
# the preload demo board, so a fresh install opens with something on screen
if DEMO.is_dir():
    for f in DEMO.iterdir():
        if f.is_file():
            datas.append((str(f), "examples/preload_example"))
# window/taskbar icon (the exe icon below covers the desktop shortcut)
datas.append((str(ROOT / "packaging" / "srm-cam-256.png"), "assets"))
# the KiCad build-area plugin, so the installed app can offer to set it up.
# Sub-folders are walked explicitly: PyInstaller's datas takes files, and the
# plugin is a package (srm20area/) rather than a flat folder.
for f in KICAD_PLUGIN.rglob("*"):
    if f.is_file() and "__pycache__" not in f.parts:
        datas.append((str(f), str(Path("kicad-plugin") / f.relative_to(KICAD_PLUGIN).parent)))

# ---- modules imported dynamically (not seen by static analysis) ----------
hiddenimports = []
hiddenimports += collect_submodules("gerber2rml")  # backends/engine registries
hiddenimports += collect_submodules("pyqtgraph")
hiddenimports += collect_submodules("OpenGL")      # PyOpenGL platform/back ends
hiddenimports += collect_submodules("gerbonara")
hiddenimports += ["qrcode"]                        # phone photo QR (function-level import)

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
    icon=str(ROOT / "packaging" / "srm-cam.ico"),   # regen: packaging/gen_icon.py
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
