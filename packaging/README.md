# Packaging SRM-CAM into a Windows installer

Turns the Python app into a downloadable **`SRM-CAM-Setup-<version>.exe`** that a
user runs to install the program (Start-menu shortcut, optional desktop icon,
uninstaller) — no Python required on their machine.

## TL;DR

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Output: `dist_installer\SRM-CAM-Setup-0.0.1.exe`.

## How it works

Two stages, both driven by `build.ps1`:

1. **PyInstaller** (`srm-cam.spec`) freezes the app + interpreter + all deps into
   a one-folder bundle at `dist\SRM-CAM\` (`SRM-CAM.exe` + `_internal\`).
2. **Inno Setup** (`installer.iss`) wraps that folder into a single `Setup.exe`
   in `dist_installer\`.

### Isolated build venv — important

`build.ps1` builds inside a dedicated venv at `.build-venv\` created from the
deps in `requirements-build.txt`. This is deliberate: building from a fat
environment (e.g. the miniconda base, which has torch/scipy/pygame) makes
PyInstaller bundle all of it and bloats the installer to multiple GB. The clean
venv keeps the bundle to just what the app needs.

The venv is created automatically on first run. After changing dependencies,
rebuild it:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Recreate
```

## Prerequisites

- **Python 3.13** (standalone CPython) to seed the build venv. Override the base
  with `-BasePython <path>` if yours is elsewhere.
- **Inno Setup 6** for stage 2. Install once:
  `winget install --id JRSoftware.InnoSetup -e`
  (Build still produces the app folder without it; it just skips `Setup.exe`.)

## Common tasks

| Goal | Command |
|---|---|
| Full installer | `build.ps1` |
| App folder only (skip Inno) | `build.ps1 -SkipInstaller` |
| Rebuild venv after dep change | `build.ps1 -Recreate` |
| Bump version | edit `MyAppVersion` in `installer.iss` (and `pyproject.toml`) |

## Files

| File | Role |
|---|---|
| `build.ps1` | Orchestrator: venv → PyInstaller → Inno Setup |
| `srm-cam.spec` | PyInstaller recipe (datas, hidden imports, excludes) |
| `installer.iss` | Inno Setup recipe (shortcuts, uninstaller, AppId) |
| `requirements-build.txt` | Exact runtime deps for the isolated build venv |
| `launcher.py` | Frozen-app entry point → `gerber2rml.gui.app:main` |

## Notes / gotchas

- `console=False` in the spec hides the terminal. To debug a crash-on-launch,
  flip it to `True`, rebuild with `-SkipInstaller`, and run
  `dist\SRM-CAM\SRM-CAM.exe` from a terminal to see the traceback.
- The preload demo board is bundled as data and resolved via `sys._MEIPASS`
  (see `_demo_dir()` in `gerber2rml/gui/app.py`), so a fresh install still opens
  with a board on screen.
- `AppId` in `installer.iss` is a fixed GUID — never change it, or upgrades will
  install side-by-side instead of replacing.
- Build artifacts (`build/`, `dist/`, `dist_installer/`, `.build-venv/`) are
  gitignored.
