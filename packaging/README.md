# Packaging SRM-CAM

Three builds from one spec (`srm-cam.spec`): a Windows installer, a Linux
AppImage (`build.sh`) and a macOS disk image ([below](#macos)). The rest of this
page up to there is the Windows one, which the other two mirror.

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
| `build.sh` | The same for Linux: venv → PyInstaller → AppImage |
| `build_macos.sh` | The same for macOS: venv → PyInstaller → disk image |
| `srm-cam.spec` | PyInstaller recipe (datas, hidden imports, excludes) |
| `installer.iss` | Inno Setup recipe (shortcuts, uninstaller, AppId) |
| `requirements-lock.txt` | **Pinned** deps — what the build actually installs |
| `requirements-lock-linux.txt`, `requirements-lock-macos.txt` | The same, for those builds |
| `requirements-build.txt` | Loose ranges the lock is regenerated from |
| `launcher.py` | Frozen-app entry point → `gerber2rml.gui.app:main` |

## macOS

`packaging/build_macos.sh`, on a Mac, or the `dmg` job in
`.github/workflows/build.yml` from anywhere. It makes `dist/SRM-CAM.app` with
PyInstaller, and puts it with a link to `/Applications` on a compressed disk image
with `hdiutil`: open it, drag the app across. Nothing else to install.

| Output | For |
|---|---|
| `SRM-CAM-<version>-macos-arm64.dmg`, `SRM-CAM-macos-arm64.dmg` | Apple Silicon |
| `SRM-CAM-<version>-macos-x86_64.dmg`, `SRM-CAM-macos-x86_64.dmg` | Intel |

**Why two images and not one.** A universal2 app needs universal2 builds of every
compiled package, and numpy, shapely and matplotlib publish separate arm64 and
x86_64 wheels instead (PySide6 alone is universal2). So CI builds once on each.
The Intel leg runs on `macos-15-intel`, the last Intel image GitHub offers; it goes
in fall 2027, and the Intel build goes with it.

**Oldest macOS: 14.** numpy's wheel at the pin is tagged `macosx_14_0` on both
architectures, and `LSMinimumSystemVersion` in the spec says so, so the Finder
refuses an older Mac with a message rather than the app crashing. PySide6 itself
would go back to 13. Raising the numpy pin can raise this.

**The lock.** `requirements-lock-macos.txt` is the Linux pins plus `macholib`, the
one thing PyInstaller needs only on a Mac. It was checked from Linux with `pip
install --dry-run --only-binary=:all: --platform macosx_15_0_arm64` (and `x86_64`):
every pin has a wheel. It has not been frozen on a Mac. The `dmg` job prints `pip
freeze`, which is the list to compare it with.

**`packaging/srm-cam.icns`** comes from `gen_icon.py`, which writes the format
itself, so regenerating it needs no Mac.

### Gatekeeper, for an unsigned app

The app is ad-hoc signed, which an Apple Silicon Mac requires before it will run
anything, but it is not signed by a known developer or notarized by Apple. A student
who downloads it through a browser gets one of two refusals on the first launch:

- *"SRM-CAM" cannot be opened / Apple could not verify it.* Try to open it once, then
  **System Settings ▸ Privacy & Security**, scroll down, **Open Anyway**. Since macOS
  15, right-click ▸ Open no longer gets past this.
- *"SRM-CAM" is damaged and can't be opened.* It is not damaged; this is how
  quarantine meets an ad-hoc signature on Apple Silicon. In Terminal, once:
  `xattr -dr com.apple.quarantine /Applications/SRM-CAM.app`

No real Mac has been through this yet, so the exact wording is from Apple's behaviour
as documented, not from watching it. Correct this section after the first real run.

### What proper signing would need

It would make both refusals go away, and needs a decision and money rather than code:

1. **An Apple Developer Program membership**: US$99 a year, in a person's or an
   organisation's name. DTU would need its D-U-N-S number for an organisation
   account, and the certificate outlives a graduating student only if it does.
2. A **Developer ID Application** certificate, exported as a `.p12`, in CI secrets.
3. In the build: `codesign --force --deep --options runtime --timestamp --sign
   "Developer ID Application: …" --entitlements <file>`. The hardened runtime needs
   an entitlements file for Python and Qt: at least
   `com.apple.security.cs.allow-unsigned-executable-memory` and
   `com.apple.security.cs.disable-library-validation`.
4. **Notarization**: `xcrun notarytool submit SRM-CAM.dmg --wait` with an app-specific
   password or an API key in CI secrets, then `xcrun stapler staple SRM-CAM.dmg`.

None of this is wired up, because there is nothing to sign with yet.

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
