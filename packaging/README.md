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

`build.ps1` builds inside a dedicated venv at `.build-venv\` created from
**`requirements-lock.txt`**. This is deliberate on two counts:

- **Clean** — building from a fat environment (e.g. the miniconda base, which
  has torch/scipy/pygame) makes PyInstaller bundle all of it and bloats the
  installer to multiple GB.
- **Pinned** — every version, including transitives, is exact. A rebuild years
  from now produces the same app instead of whatever PyPI serves that day.
  `requirements-build.txt` holds the loose ranges the lock is generated from.

The venv is created automatically on first run. After changing dependencies,
rebuild it:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Recreate
```

## Prerequisites

- **Python 3.12** (standalone CPython) to seed the build venv — the version the
  lock is verified against and what CI builds with. Defaults to the first
  `python` on PATH; override with `-BasePython <path>`.
- **Inno Setup 6** for stage 2. Install once:
  `winget install --id JRSoftware.InnoSetup -e`
  (Build still produces the app folder without it; it just skips `Setup.exe`.)

## Common tasks

| Goal | Command |
|---|---|
| Full installer (+ version-less copy) | `build.ps1` |
| App folder only (skip Inno) | `build.ps1 -SkipInstaller` |
| Rebuild venv after dep change | `build.ps1 -Recreate` |
| Upgrade a dep (unpinned) | `build.ps1 -Recreate -Loose`, then re-freeze the lock |
| Bump version | edit all **three**: `pyproject.toml`, `installer.iss`, `gerber2rml/__init__.py` |
| Check the version agrees | `python scripts/check_version.py` |

## Publishing a release

`build.ps1` produces **two** files in `dist_installer\`:

- `SRM-CAM-Setup-<version>.exe` — the normal versioned installer.
- `SRM-CAM-Setup.exe` — an identical **version-less** copy.

**Both are uploaded** as release assets. The DTU-PCB-prototyping guide links to
a permanent one-click URL —
`https://github.com/MadsRudolph/srm-cam/releases/latest/download/SRM-CAM-Setup.exe`
— which only resolves if the latest release contains an asset named **exactly**
`SRM-CAM-Setup.exe`. Skip it and that download link 404s.

The tag-push flow handles this. Steps:

1. Bump the version in **all three** files (CI fails the build otherwise).
2. `git tag v<version> && git push --tags`
3. Watch **Actions → build installer**. It checks the tag matches the version,
   builds, verifies the installer is a plausible size, writes `SHA256SUMS.txt`,
   and opens a **draft** release with all three assets.
4. Review the draft and publish it.

To rehearse without releasing: **Actions → build installer → Run workflow**.
That produces the same installer as a downloadable artifact and creates no
release — the way to confirm the build still works after a dependency bump.

## Files

| File | Role |
|---|---|
| `build.ps1` | Orchestrator: venv → PyInstaller → Inno Setup |
| `srm-cam.spec` | PyInstaller recipe (datas, hidden imports, excludes) |
| `installer.iss` | Inno Setup recipe (shortcuts, uninstaller, AppId) |
| `requirements-lock.txt` | **Pinned** deps — what the build actually installs |
| `requirements-build.txt` | Loose ranges the lock is regenerated from |
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
