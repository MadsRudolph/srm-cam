# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SRM-CAM (gerber2rml GUI).

Build (from the repo root, with the miniconda env that has the GUI deps):
    python -m PyInstaller --noconfirm packaging/srm-cam.spec

Produces a one-folder app at dist/SRM-CAM/ (SRM-CAM.exe + _internal/).
The Inno Setup script (packaging/installer.iss) wraps that folder into Setup.exe.
On macOS it also wraps the folder into dist/SRM-CAM.app (packaging/build-macos.sh).

One-folder (not one-file) is deliberate: faster cold start (no temp unpack of a
~400 MB archive every launch) and the installer bundles the folder anyway.
"""
import sys
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
# macOS: where this build was made from, so Help > Check for updates can
# rebuild it from the same checkout (gui2/updatecheck.py).
if sys.platform == "darwin":
    import json
    _info = ROOT / "build" / "macos" / "build_info.json"
    _info.parent.mkdir(parents=True, exist_ok=True)
    _info.write_text(json.dumps({"repo": str(ROOT)}), encoding="utf-8")
    datas.append((str(_info), "."))
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

# ---- macOS: pyusb and the libusb it loads --------------------------------
# engine/millsetup.py reads and sets the mill's own settings over USB control
# transfers. pyusb is imported inside a function and loads libusb by name at
# run time, so PyInstaller sees neither: the module is named here and the
# library is copied in beside the executable, where millsetup looks first.
# Without Homebrew's libusb the app still builds; the Machine menu then says
# what is missing instead of reading the mill.
binaries = []
if sys.platform.startswith("linux"):
    # Linux: libusb is part of every desktop install (udev depends on it), so
    # only the Python side is bundled and the system's libusb is loaded.
    hiddenimports += ["usb", "usb.core", "usb.backend.libusb1"]
if sys.platform == "darwin":
    hiddenimports += ["usb", "usb.core", "usb.backend.libusb1"]
    for _lib in (Path("/opt/homebrew/lib/libusb-1.0.0.dylib"),
                 Path("/usr/local/lib/libusb-1.0.0.dylib")):
        if _lib.is_file():
            binaries.append((str(_lib), "."))
            break

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
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
    # PyInstaller only consumes an icon on Windows and macOS; on Linux the
    # AppImage takes its icon from the .desktop entry instead. Passing a .ico
    # there is ignored with a warning, and a spec should not ask for something
    # it knows is meaningless.
    icon=(str(ROOT / "packaging" / "srm-cam.ico")
          if sys.platform.startswith("win") else None),
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

# ---- macOS: wrap the folder into an .app ---------------------------------
# build-macos.sh makes the .icns (sips + iconutil) into build/macos/ first;
# without it the bundle simply gets the default icon.
if sys.platform == "darwin":
    import tomllib
    _icns = ROOT / "build" / "macos" / "srm-cam.icns"
    _version = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["version"]
    app = BUNDLE(
        coll,
        name="SRM-CAM.app",
        icon=str(_icns) if _icns.is_file() else None,
        bundle_identifier="io.github.madsrudolph.srm-cam",
        version=_version,
        info_plist={
            "CFBundleDisplayName": "SRM-CAM",
            "CFBundleShortVersionString": _version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
