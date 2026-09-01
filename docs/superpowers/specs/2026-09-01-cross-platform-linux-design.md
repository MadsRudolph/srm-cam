# Cross-platform — running SRM-CAM on Linux without giving up Windows

*Written 2026-09-01, against `feat/setup-sheet-gui` @ `7b2a3c0` (v0.4.0).
Baseline measured on that commit: **880 passed** in 6:28, CPython 3.13.3.*

The CNC PC is Windows and always will be. The machine that prepares the jobs is
now Fedora, and the students who inherit this will be on Fedora or Ubuntu. So
the program has to be genuinely at home on both, and both installers have to
produce something that works — not a Windows build with a Linux escape hatch.

---

## 1. What is already portable

Worth stating first, because it makes this a much smaller job than it sounds.

The engine is pure Python over `gerbonara` and `shapely`. Nothing in
`engine/`, `app/`, `backends/`, `cli.py` or `doublesided.py` touches an OS
API. Every GUI dependency — PySide6, matplotlib, pyqtgraph, PyOpenGL, pyserial,
qrcode — ships Linux wheels for the versions already pinned.

Three things that could have been Windows-shaped and are not:

- **The workspace path.** `gui/workspace.py` and `gui2/workspace.py` both go
  through `QStandardPaths.writableLocation(DocumentsLocation)` with a
  `Path.home()` fallback, and both honour `SRM_CAM_HOME`. On Linux that reads
  the XDG user-dirs config and returns the right thing.
- **Port ranking.** `spi_probe.rank_ports` matches on USB VID (`VID:PID=` /
  `VID_`), and pyserial reports those identically on Linux. The CH340 that the
  lab's Uno clone uses is recognised on both platforms by the same code.
- **KiCad config discovery.** `engine/kicadplugin.config_roots` already takes
  `platform`, `env` and `home` arguments and already has the Linux branch
  (`~/.config/kicad`). It is the model the rest of this spec follows.

Nothing fails at import on Linux today. pyserial is lazily imported everywhere
— `engine/spi_probe.py:21` says so explicitly, and `gui2/machine.py:list_ports`
catches the `ImportError` and returns a sentence explaining it rather than an
empty dropdown.

---

## 2. Scope

Two decisions were taken before this spec was written.

**The Linux installer is an AppImage.** One file, `chmod +x`, run. No root, no
per-distro build, no system-Qt version skew, and it works the same on Fedora,
Ubuntu, Mint and Arch. It is the closest analogue to the `Setup.exe` students
already download. The cost is a ~400 MB file and manual desktop-menu
integration, which is the right trade for an audience that downloads the thing
once a semester.

**Linux is for preparing jobs, not for driving the mill.** Load Gerbers, run
the checks, generate toolpaths, export `.nc`. The machine link — connect, DRO,
jog, bed levelling, firmware flashing — stays a Windows capability. This
matches the hardware reality, it is fully testable without a mill, and it
avoids shipping an unverified motion path to a student standing next to a
spinning tool. Serial support can be added later without redesigning anything
here.

### Explicitly out of scope

- Flatpak, `.deb`, `.rpm`. One Linux artifact.
- macOS. Nothing here blocks it, and `config_roots` already has a `darwin`
  branch, but it is not a target and will not be tested.
- Making the serial link work on Linux. Section 5 says what the machine page
  does instead.

---

## 3. `gerber2rml/platform.py`

One module owns every platform difference. This is not a stylistic preference
— it is the pattern this repo already enforces twice:

- `gui2/theme.py` owns every colour, and `tests/test_gui2_theme.py` fails if a
  hex literal appears anywhere else in the package.
- `gui2/runplan.py` owns the run order, and its test fails if `cli.build_jobs`
  writes a file the plan does not know about.

The failure mode a central module prevents is already in the tree: `"COM5"`
appears **8 times** in `gui/app.py` — six `or "COM5"` fallbacks (lines 489,
3693, 4122, 4260, 4415, 6175) and two combo-box seeds (922, 924). Eight places
to fix and eight places for the next one to be missed.

### Interface

Every function takes an optional `platform=` argument defaulting to
`sys.platform`, mirroring `kicadplugin.config_roots(platform=None, env=None,
home=None)`. Tests inject `"linux"` or `"win32"` and run identically on any
host — no `skipif`, no host-dependent assertions.

```python
def capabilities(platform=None) -> Capabilities
    # what this OS supports. One field for now: .machine_link

def default_serial_port(platform=None) -> str | None
    # "COM5" on Windows; None on Linux — see below

def reveal(path, platform=None) -> None
    # show a file in the desktop's file manager

def arduino_cli_candidates(platform=None, env=None, home=None) -> list[Path]
    # where a bundled arduino-cli might live

def serial_permission_hint(device, platform=None) -> str | None
    # the sentence to show when opening a port fails with EACCES
```

`default_serial_port` returns `None` rather than `/dev/ttyACM0` on Linux.
Guessing a device node is worse than not guessing: `/dev/ttyACM0` may be some
other board entirely, whereas `COM5` on the lab PC is a documented convention.
Callers already handle "no port selected"; `best_port` returns `None` for
exactly this reason and its docstring explains why a guess is worse than an
honest refusal.

### `serial_permission_hint` — reading the group, not assuming it

On a fresh Fedora or Ubuntu user account, opening `/dev/ttyACM0` fails with
`PermissionError`. This is invisible on Windows and it is the single most
likely "the Linux version doesn't work" report.

The hint **stats the device and reads its actual group name** rather than
hardcoding one. Fedora and Ubuntu both use `dialout` today, but Arch uses
`uucp` and a hardcoded group produces advice that silently does not work. The
device knows the answer:

```python
grp.getgrgid(os.stat(device).st_gid).gr_name
```

The resulting sentence names the real group, the real command, and the fact
that it needs a re-login:

> `/dev/ttyACM0` is owned by the `dialout` group and you are not in it.
> Run `sudo usermod -aG dialout $USER`, then log out and back in.

This lands in scope even though the machine link is Windows-only, because
`flash_firmware.py` and any future serial work both need it, and because
a student who plugs a board in and gets a bare `PermissionError` is exactly
the case this project's §3.6 ("errors say what to do") exists to prevent.

---

## 4. The localised-Documents divergence

A real bug, found while writing this spec, that only shows up on a non-English
Linux desktop — which is to say, on the Danish Fedora install this is for.

`gui2/app.py:_log_path()` computes `Path.home() / "Documents"` directly, with a
fallback to `Path.home()`. It cannot use `QStandardPaths`, and deliberately so:
it runs *before* PySide6 is imported, because its whole job is to catch a
traceback raised while importing PySide6.

`workspace.workspace_root()` uses `QStandardPaths.DocumentsLocation`, which
reads `XDG_DOCUMENTS_DIR` from `~/.config/user-dirs.dirs`.

On a Danish desktop that directory is `~/Dokumenter`. So:

| | resolves to |
|---|---|
| `workspace_root()` | `~/Dokumenter/SRM-CAM/` |
| `_log_path()` | `~/SRM-CAM/gui2.log` |

The workspace and the startup log end up in different folders, and the log —
whose entire purpose is to be findable when the app will not start — is the one
in the unexpected place. On Windows both agree, so no test catches it.

**Fix:** `_log_path()` reads `~/.config/user-dirs.dirs` itself on Linux. It is
a five-line shell-style parse of a file that may not exist, with the current
`Path.home()` fallback unchanged when it does not. `SRM_CAM_HOME` still wins,
as it does today.

This is small, but it belongs in this spec rather than a follow-up: the first
thing anyone does when the AppImage does not launch is look for the log.

---

## 5. The machine half on Linux

Two facts make this cheap and honest rather than a hole in the product.

**pyserial is already optional.** Nothing needs restructuring for the machine
code to be absent — `gui2/machine.py:list_ports` already returns a reason
instead of an empty list, and the pattern extends naturally to "this platform
does not support the link" as another reason.

**A height map is a file, not a live connection.** `gui/app.py:3634`
(`_on_load_level_grid`) already loads a probe-grid CSV from disk, and
`_height_map()` feeds it into export exactly the same way a freshly probed grid
would. Linux therefore loses the ability to *measure* a bed, not the ability to
*apply* one.

That makes the supported workflow a real workflow rather than a workaround:

1. Probe the bed once on the Windows CNC PC, export the grid as CSV.
2. Keep the CSV with the board's session files.
3. On Linux, load it and export levelled toolpaths as normal.

The machine page on Linux says exactly that — a sentence naming the platform
limitation and pointing at *Load height map…* — rather than showing controls
that cannot work. It is not greyed out with no explanation; per §2.4 of the A/B
doc, a dead control with no reason is the thing this project refuses to ship.

`capabilities().machine_link` gates it, so the Windows behaviour is
byte-identical to today and the Linux behaviour is one branch in one place.

---

## 6. Call sites to change

| file | what | change |
|---|---|---|
| `gui/app.py` ×8 | `"COM5"` literals | `platform.default_serial_port()`; the two `addItem` seeds only add an entry when it is not `None` |
| `gui2/window.py:1625` | `explorer /select,` | `platform.reveal()`; gains `xdg-open`, keeps the existing `QDesktopServices` fallback |
| `gui2/app.py:28` | `Path.home()/"Documents"` | XDG-aware, per §4 |
| `scripts/flash_firmware.py:42` | `LOCALAPPDATA` arduino-cli | `platform.arduino_cli_candidates()` |
| `scripts/flash_firmware.py` | `Documents/Arduino/libraries` | XDG-aware; Linux IDE uses `~/Arduino/libraries` |

`flash_firmware.py` is a developer script, not a shipped feature, so it gets
working paths on Linux but no further guarantees.

---

## 7. Packaging

### The PyInstaller spec

`packaging/srm-cam.spec` is close to portable already. Two changes:

- `icon=` is Windows/macOS only. PyInstaller warns and ignores it on Linux, but
  the spec should not pass a `.ico` it knows is meaningless — make it
  conditional on `sys.platform`.
- `name="SRM-CAM"` produces `SRM-CAM.exe` on Windows and `SRM-CAM` on Linux,
  which is correct and needs nothing.

Everything else — the `datas` list, the `hiddenimports`, the `excludes` that
keep a second Qt binding out — applies unchanged.

### `packaging/build.sh`

Mirrors `build.ps1` stage for stage, so the two are comparable when one breaks:
isolated `.build-venv` from the pinned lock, PyInstaller to `dist/SRM-CAM/`,
then AppImage instead of Inno Setup. Same `--recreate` / `--loose` /
`--skip-installer` switches, spelled the POSIX way.

### The AppImage

`linuxdeploy` with its Qt plugin over the PyInstaller one-folder output. Needs
two new files:

- `packaging/srm-cam.desktop` — standard desktop entry.
  `Categories=Development;Engineering;`, `MimeType` left off for now.
- the icon, which already exists: `packaging/srm-cam-256.png`.

Output: `dist_installer/SRM-CAM-<version>-x86_64.AppImage`.

`packaging/build.ps1` and `packaging/installer.iss` are **not touched**. The
Windows artifact must come out of this work bit-identical in every respect that
matters.

### Two lock files

`packaging/requirements-lock.txt` is Windows-resolved — it pins
`pywin32-ctypes==0.2.3` under a "pyinstaller / windows" heading, and it is
missing the transitives PyInstaller pulls in on Linux.

Add `packaging/requirements-lock-linux.txt`, generated the same way and
carrying the same header explaining how to regenerate it.

One lock per shipped artifact, rather than one file with environment markers,
because the existing lock's header makes a specific promise — *"a rebuild in
five years produces the same app instead of whatever PyPI happens to serve that
day"* — and a marker-based file is only ever resolved on one platform at a
time. Two files keep that promise on both. The cost is that upgrading a
dependency means regenerating two locks, which the header of each will say.

---

## 8. CI

`.github/workflows/tests.yml` — the gating `locked` job becomes a matrix over
`[windows-latest, ubuntu-latest]`, each installing its own lock. `QT_QPA_PLATFORM: offscreen`
and `QT_OPENGL: software` are already set at workflow level and are exactly
what a headless Linux runner needs, so no change there. The monthly `canary`
job gets the same matrix; it installs unpinned, so it needs no second lock.

Linux CI may need one step Windows does not: an `apt-get` of the system
libraries Qt links against. PySide6's wheels bundle Qt itself but not
everything Qt loads from the host, and a bare `ubuntu-latest` image is
minimal. `offscreen` avoids the X11 platform plugin and so avoids most of it,
but QtGui still pulls in EGL/xkbcommon on some images regardless of the
platform plugin.

**Do not guess the list.** Run the suite on a clean runner first and add only
what it actually asks for. A speculative `apt-get install` of a dozen `libxcb-*`
packages is how this step becomes cargo-cult and stays that way for years. The
failure mode is loud and specific (`could not load the Qt platform plugin`), so
it is cheap to discover empirically and expensive to guess at.

`.github/workflows/build.yml` gains a `linux` job producing the AppImage and
uploading it to the same draft release as the Windows installer.

`scripts/check_version.py` currently asserts three files agree. The `.desktop`
file carries no version, so it needs no fourth check — but the AppImage
filename is derived from `pyproject.toml`, so the existing check already covers
it. No change.

---

## 9. Testing

The 880 existing tests stay green on Windows. That is the gate: this work is
not allowed to change Windows behaviour, and the golden-file tests
(`tests/test_golden.py`) will catch it at the RML level if it does.

New tests, all host-independent by construction:

- **`tests/test_platform.py`** — every `platform.py` function against injected
  `"win32"` and `"linux"`, including `default_serial_port` returning `None` on
  Linux and `capabilities().machine_link` being False there.
- **The guard test** — no bare `sys.platform` outside `gerber2rml/platform.py`,
  modelled directly on `test_gui2_theme.py`'s no-hex-literals check.
  `engine/kicadplugin.py` is the one allowed exception and is named in the
  test, since its `config_roots` predates this module and already does the
  right thing.
- **`serial_permission_hint`** against a fake `stat` result, asserting it names
  the group it was given rather than a hardcoded `dialout`.
- **The XDG log path** — `_log_path()` against a temp `user-dirs.dirs`
  declaring a non-English documents folder, asserting the log and the workspace
  agree.
- **A Linux machine-page test** — `capabilities().machine_link` False produces
  the explanatory sentence and does not construct the link controls.

Ubuntu CI is what proves the suite genuinely runs on Linux rather than merely
being written to.

---

## 10. What this does not prove

Stated plainly, in the spirit of §8 and §11 of `docs/AB-setup-sheet.md`.

- **The AppImage has never been run.** CI can build one and check it is
  produced and non-empty; it cannot confirm it launches on a real Fedora
  desktop with a real GPU. First launch on the Fedora machine is the
  acceptance test, and until that has happened this is unproven.
- **Nothing here is tested against a mill on Linux**, by design — the machine
  link is off on that platform. If it is ever turned on, everything in §2.5 and
  §2.7 of `docs/HANDOFF-gui-ab.md` applies again from scratch.
- **The Wayland question is open.** Fedora 44 with Hyprland means Qt will pick
  the Wayland backend if it is available and fall back to XWayland otherwise.
  Qt 6.11 handles both, but the 3D views (`pyqtgraph` over PyOpenGL) are the
  place where a compositor difference would show up first, and no one has
  looked. Worth a deliberate check on first launch rather than an assumption.
- **`serial_permission_hint` is written against documented behaviour** and
  tested against a fake stat. It has not been run against a real
  permission-denied device.

---

## 11. Files

**New:** `gerber2rml/platform.py`, `tests/test_platform.py`,
`packaging/build.sh`, `packaging/srm-cam.desktop`,
`packaging/requirements-lock-linux.txt`.

**Changed:** `gui/app.py` (8 sites), `gui2/window.py`, `gui2/app.py`,
`gui2/machine.py`, `scripts/flash_firmware.py`, `packaging/srm-cam.spec`,
`.github/workflows/tests.yml`, `.github/workflows/build.yml`, `README.md`,
`docs/usage.md`.

**Untouched, deliberately:** `packaging/build.ps1`, `packaging/installer.iss`,
`packaging/requirements-lock.txt`, and everything under `engine/`, `app/`,
`backends/`, `cli.py`, `doublesided.py`.
