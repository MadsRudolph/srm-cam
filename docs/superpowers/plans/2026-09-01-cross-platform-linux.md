# Cross-Platform Linux Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SRM-CAM runs natively on Fedora and Ubuntu for preparing jobs, ships as an AppImage, and the Windows build comes out unchanged.

**Architecture:** One new module, `gerber2rml/platform.py`, owns every platform difference; every other file asks it. A guard test forbids bare `sys.platform` anywhere else, mirroring how `tests/test_gui2_theme.py` forbids hex literals outside `theme.py`. The machine link stays Windows-only behind `capabilities().machine_link`. Packaging gains a parallel Linux track (`build.sh` → AppImage) beside the untouched Windows one.

**Tech Stack:** Python 3.10+, PySide6, PyInstaller, linuxdeploy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-01-cross-platform-linux-design.md`

## Global Constraints

- **Branch:** `feat/cross-platform-linux`, forked from `feat/setup-sheet-gui` @ `7b2a3c0`.
- **Baseline:** 880 tests pass. Every task ends with the suite still at ≥880 passing. Run: `python -m pytest -q`.
- **Windows behaviour must not change.** `tests/test_golden.py` compares generated RML byte-for-byte; if it moves, the task is wrong.
- **No AI attribution in commits.** Commit messages read like a developer wrote them. (`CLAUDE.md`, hard rule.)
- **`platform.py` imports no Qt and no third-party package.** stdlib only. It is imported by `engine/`-level code and by `gui2/app.py` *before* PySide6 is importable.
- **Every `platform.py` function takes `platform=None`** defaulting to `sys.platform`, mirroring `engine/kicadplugin.py:config_roots(platform=None, env=None, home=None)`. Tests inject `"win32"` / `"linux"` — never `skipif` on the host OS.
- **`grp` and `pwd` are POSIX-only.** Importing either at module scope breaks the Windows build. Import inside the branch that uses it.
- **Interpreter on this machine:** `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe`. The bare `python` on PATH is the Store 3.11 and has no PySide6.

## Execution split

**Part A (Tasks 1–10)** runs on Windows, here, now. Fully verifiable — the 880 suite covers it.

**Part B (Tasks 11–14)** requires a Linux host. `requirements-lock-linux.txt` is a `pip freeze` on Linux and cannot be produced on Windows; the AppImage build and the first-launch check likewise. Do Part A first, push, then pick Part B up on the Fedora machine.

---

# Part A — runs on Windows

### Task 1: `platform.py` — capabilities, serial port, reveal

**Files:**
- Create: `gerber2rml/platform.py`
- Test: `tests/test_platform.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `capabilities(platform=None) -> Capabilities` with field `.machine_link: bool`; `default_serial_port(platform=None) -> str | None`; `reveal_command(path, platform=None) -> list[str] | None`. Module constants `WINDOWS = "win32"`, `LINUX = "linux"`, `MACOS = "darwin"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_platform.py`:

```python
"""Platform differences have one home, and these tests keep them there.

Every assertion injects a platform string rather than reading the host's, so
the Linux behaviour is tested on Windows and vice versa. A test that only
passes on the machine it was written on proves nothing about the other one.
"""
from pathlib import Path

from gerber2rml import platform as plat


def test_machine_link_is_windows_only():
    assert plat.capabilities("win32").machine_link is True
    assert plat.capabilities("linux").machine_link is False
    assert plat.capabilities("darwin").machine_link is False


def test_default_serial_port_is_com5_on_windows():
    assert plat.default_serial_port("win32") == "COM5"


def test_default_serial_port_refuses_to_guess_off_windows():
    """A guess at /dev/ttyACM0 may be some other board entirely, and produces
    a confusing timeout. spi_probe.best_port returns None for the same reason."""
    assert plat.default_serial_port("linux") is None
    assert plat.default_serial_port("darwin") is None


def test_reveal_selects_the_file_on_windows():
    cmd = plat.reveal_command(Path(r"C:\work\board_traces.nc"), "win32")
    assert cmd[0] == "explorer"
    assert "board_traces.nc" in cmd[-1]


def test_reveal_has_no_command_off_windows():
    """xdg-open cannot select a file, only open a folder - so there is nothing
    better here than the caller's existing QDesktopServices fallback, and
    returning None says so rather than pretending."""
    assert plat.reveal_command(Path("/home/mads/board.nc"), "linux") is None


def test_capabilities_defaults_to_the_running_host():
    import sys
    assert plat.capabilities().machine_link == sys.platform.startswith("win")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gerber2rml.platform'`

- [ ] **Step 3: Write the minimal implementation**

Create `gerber2rml/platform.py`:

```python
"""Everything this program needs to know about the OS it is running on.

One module, for the same reason ``gui2/theme.py`` is one module: a difference
spelled out at each call site is invisible until it has a name, and one nobody
can find is one nobody can fix. The evidence was already in the tree - "COM5"
appeared eight times in ``gui/app.py``, six as a fallback and twice as a
combo-box seed. Eight places, and eight chances for the next one to be missed.

Every function takes an optional ``platform`` argument defaulting to
``sys.platform``, mirroring :func:`gerber2rml.engine.kicadplugin.config_roots`.
Tests inject ``"win32"`` or ``"linux"`` and so run identically on any host.

stdlib only, and no Qt. This module is imported by ``gui2/app.py`` before
PySide6 is imported - that import is precisely what it exists to survive.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

WINDOWS = "win32"
LINUX = "linux"
MACOS = "darwin"


def _plat(platform=None):
    return sys.platform if platform is None else platform


def _is_windows(platform=None):
    return _plat(platform).startswith("win")


@dataclass(frozen=True)
class Capabilities:
    """What the host OS supports.

    One field for now. It is a dataclass rather than a bare bool so that
    adding a second capability does not change every call site.
    """
    machine_link: bool


def capabilities(platform=None):
    """What this OS supports.

    ``machine_link`` is the Arduino serial link - connect, DRO, jog, bed
    probing, firmware flashing. Windows only, deliberately: the CNC PC is
    Windows, the link has only ever been run there, and shipping an unverified
    motion path to someone standing next to a spinning tool is not a trade
    worth making. Losing it costs less than it looks, because a height map is
    a file: measure the bed once on the CNC PC and carry the CSV.
    """
    return Capabilities(machine_link=_is_windows(platform))


def default_serial_port(platform=None):
    """The port to fall back to when nothing is selected, or None.

    ``None`` off Windows rather than a guess at ``/dev/ttyACM0``: that node may
    be some other board entirely, and probing the wrong port produces a
    timeout that tells the user nothing. ``spi_probe.best_port`` returns None
    for exactly this reason and its docstring explains it. ``COM5`` on Windows
    is a documented lab convention, not a guess.
    """
    return "COM5" if _is_windows(platform) else None


def reveal_command(path, platform=None):
    """Argv that shows ``path`` selected in the file manager, or None.

    None off Windows on purpose. ``xdg-open`` opens a folder but cannot select
    a file inside it, which is exactly what the caller's existing
    ``QDesktopServices`` fallback already does - so there is nothing better to
    return here, and None says so instead of pretending.
    """
    if _is_windows(platform):
        return ["explorer", "/select,", str(Path(path))]
    return None
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/platform.py tests/test_platform.py
git commit -m "platform: one home for the differences between Windows and Linux

COM5 was in gui/app.py eight times - six fallbacks and two combo seeds - which
is the argument for a module rather than a check per call site, and the same
argument gui2/theme.py already won for colour.

Every function takes an injectable platform string, mirroring
kicadplugin.config_roots, so the Linux behaviour is tested on Windows rather
than skipped there. stdlib only and no Qt: gui2/app.py imports this before it
imports PySide6, which is the import it exists to survive.

default_serial_port returns None off Windows rather than guessing
/dev/ttyACM0. That node may be another board, and a wrong guess produces a
timeout that says nothing - best_port already refuses to guess for the same
reason."
```

---

### Task 2: `serial_permission_hint` — read the group, don't assume it

**Files:**
- Modify: `gerber2rml/platform.py`
- Test: `tests/test_platform.py`

**Interfaces:**
- Consumes: `_plat`, `_is_windows` from Task 1.
- Produces: `serial_permission_hint(device, platform=None, stat_fn=None, group_fn=None) -> str | None`.

**Why this is in scope even though the link is Windows-only:** `flash_firmware.py` needs it, any future serial work needs it, and a student who plugs a board into Fedora and gets a bare `PermissionError` is the exact case §3.6 of the A/B doc ("errors say what to do") exists to prevent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_platform.py`:

```python
def test_permission_hint_names_the_group_the_device_actually_has():
    """Fedora and Ubuntu use dialout; Arch uses uucp. Advice naming the wrong
    group is advice that silently does not work, which is worse than none - so
    the group is read off the device rather than assumed."""
    hint = plat.serial_permission_hint(
        "/dev/ttyACM0", "linux",
        stat_fn=lambda p: type("st", (), {"st_gid": 986})(),
        group_fn=lambda gid: "uucp")
    assert "uucp" in hint
    assert "dialout" not in hint
    assert "sudo usermod -aG uucp" in hint
    assert "log out" in hint.lower()


def test_permission_hint_says_dialout_when_that_is_the_group():
    hint = plat.serial_permission_hint(
        "/dev/ttyACM0", "linux",
        stat_fn=lambda p: type("st", (), {"st_gid": 20})(),
        group_fn=lambda gid: "dialout")
    assert "sudo usermod -aG dialout $USER" in hint


def test_permission_hint_is_silent_on_windows():
    """Windows has no group to join; a hint here would be noise."""
    assert plat.serial_permission_hint("COM5", "win32") is None


def test_permission_hint_survives_a_device_that_is_not_there():
    """The device may have been unplugged between the failure and the hint."""
    def boom(_p):
        raise FileNotFoundError
    hint = plat.serial_permission_hint("/dev/ttyACM0", "linux", stat_fn=boom)
    assert hint is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: FAIL — `AttributeError: module 'gerber2rml.platform' has no attribute 'serial_permission_hint'`

- [ ] **Step 3: Write the minimal implementation**

Append to `gerber2rml/platform.py`:

```python
def serial_permission_hint(device, platform=None, stat_fn=None, group_fn=None):
    """What to tell someone whose serial port refused to open, or None.

    On a fresh Fedora or Ubuntu account, opening ``/dev/ttyACM0`` fails with
    PermissionError because the node is root-owned with group access and the
    user is not in that group. It is invisible on Windows, and it is the most
    likely "the Linux version doesn't work" report this project will get.

    The group is read off the DEVICE rather than hardcoded. Fedora and Ubuntu
    both use ``dialout`` today, but Arch uses ``uucp``, and telling someone to
    join a group that is not the one guarding the node is advice that fails
    silently.

    ``stat_fn`` and ``group_fn`` are injectable so the test does not need a
    real device with a real group.

    ``grp`` is POSIX-only stdlib - importing it at module scope would break the
    Windows build, so it is imported inside the branch.
    """
    if _is_windows(platform):
        return None
    import os
    stat_fn = os.stat if stat_fn is None else stat_fn
    if group_fn is None:
        import grp
        def group_fn(gid):
            return grp.getgrgid(gid).gr_name
    try:
        group = group_fn(stat_fn(device).st_gid)
    except Exception:
        # Unplugged between the failure and the hint, or a group with no name.
        # No hint is better than a wrong one.
        return None
    return (f"{device} is owned by the '{group}' group and you are not in it. "
            f"Run  sudo usermod -aG {group} $USER  then log out and back in "
            f"for the change to take effect.")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/platform.py tests/test_platform.py
git commit -m "platform: say which group guards the serial node, having looked

A fresh Fedora or Ubuntu account cannot open /dev/ttyACM0 and gets a bare
PermissionError, which is invisible on Windows and is the likeliest 'the Linux
version doesn't work' report this will get.

The group is read off the device rather than assumed. Fedora and Ubuntu use
dialout, Arch uses uucp, and naming the wrong one is advice that fails
silently - worse than none. grp is POSIX-only, so it is imported inside the
branch rather than at module scope, which would break the Windows build."
```

---

### Task 3: The eight `COM5` sites in `gui/app.py`

**Files:**
- Modify: `gerber2rml/gui/app.py` lines 489, 922, 924, 3693, 4122, 4260, 4415, 6175 and the tooltip at 912-914
- Test: `tests/test_platform.py`

**Interfaces:**
- Consumes: `default_serial_port(platform=None)` from Task 1.
- Produces: nothing new.

**Note:** six sites are `or "COM5"` fallbacks (489, 3693, 4122, 4260, 4415, 6175); two are combo-box seeds (922, 924). They need different treatment — a seed of `None` must add no item at all.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_platform.py`:

```python
def test_no_com5_literals_left_in_the_first_interface():
    """Eight of these was the reason platform.py exists. The literal belongs in
    one place now, and this fails if one grows back."""
    import re
    app = (Path(__file__).parent.parent / "gerber2rml" / "gui" / "app.py")
    offenders = [f"{i}: {line.strip()[:70]}"
                 for i, line in enumerate(
                     app.read_text(encoding="utf-8").split("\n"), 1)
                 if re.search(r'"COM\d+"', line)]
    assert not offenders, (
        "hardcoded COM port(s) - use platform.default_serial_port():\n  "
        + "\n  ".join(offenders))
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py::test_no_com5_literals_left_in_the_first_interface -q`
Expected: FAIL, listing 8 lines

- [ ] **Step 3: Write the minimal implementation**

Add the import near the top of `gerber2rml/gui/app.py`, beside the other `gerber2rml` imports:

```python
from gerber2rml import platform as plat
```

Replace each of the six fallback sites (489, 3693, 4122, 4260, 4415, 6175). They are textually identical apart from the receiver — `p.level_port_combo` at 489, `self.level_port_combo` at the rest:

```python
        # was: ... .currentText().strip() or "COM5"
        port = p.level_port_combo.currentText().strip() or plat.default_serial_port()
```

```python
        # the five self.* sites
        port = self.level_port_combo.currentText().strip() or plat.default_serial_port()
```

Replace the combo seeding at 916-924. A `None` default must add nothing — an empty editable combo is the honest Linux state:

```python
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
            if ports:
                self.level_port_combo.addItems(ports)
            else:
                fallback = plat.default_serial_port()
                if fallback:
                    self.level_port_combo.addItem(fallback)
        except Exception:
            fallback = plat.default_serial_port()
            if fallback:
                self.level_port_combo.addItem(fallback)
```

And the tooltip at 912-914, which names a Windows-only tool:

```python
        self.level_port_combo.setToolTip(
            "Serial port of the Arduino. Used by both Connect (live DRO) and "
            "the SPI bed probe."
            + (" Device Manager > Ports lists them."
               if plat.capabilities().machine_link else ""))
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q && C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: `test_platform.py` 11 passed; full suite ≥880 passed

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui/app.py tests/test_platform.py
git commit -m "gui: ask for the default serial port instead of spelling COM5

Eight sites: six fallbacks and two combo seeds. The seeds needed different
treatment from the fallbacks - a default of None must add no item at all,
because an empty editable combo is the honest state on a machine where the
link does not run, and an entry saying COM5 there is a lie.

The tooltip pointed at Device Manager, which is not a thing on Linux."
```

---

### Task 4: `_reveal` in `gui2/window.py`

**Files:**
- Modify: `gerber2rml/gui2/window.py:1623-1632`
- Test: `tests/test_gui2_window.py`

**Interfaces:**
- Consumes: `reveal_command(path, platform=None)` from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui2_window.py`:

```python
def test_reveal_spawns_no_file_manager_where_none_can_select(qt_app, tmp_path,
                                                             monkeypatch):
    """On Linux there is no command that selects a file, so _reveal must not
    spawn anything - it falls through to Qt, which opens the parent folder.
    Spawning 'explorer' there is the bug this guards."""
    from gerber2rml.gui2 import window as win
    from gerber2rml import platform as plat
    spawned = []
    monkeypatch.setattr(win.subprocess, "Popen",
                        lambda cmd, *a, **k: spawned.append(cmd))
    monkeypatch.setattr(plat, "reveal_command", lambda p, platform=None: None)
    opened = []
    monkeypatch.setattr(win.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url)))

    w = win.MainWindow()
    w._reveal(tmp_path / "board_traces.nc")

    assert spawned == []
    assert len(opened) == 1


def test_reveal_selects_the_file_where_the_file_manager_can(qt_app, tmp_path,
                                                            monkeypatch):
    from gerber2rml.gui2 import window as win
    from gerber2rml import platform as plat
    spawned = []
    monkeypatch.setattr(win.subprocess, "Popen",
                        lambda cmd, *a, **k: spawned.append(cmd))
    monkeypatch.setattr(plat, "reveal_command",
                        lambda p, platform=None: ["explorer", "/select,", str(p)])

    w = win.MainWindow()
    w._reveal(tmp_path / "board_traces.nc")

    assert len(spawned) == 1
    assert spawned[0][0] == "explorer"
```

If `MainWindow` needs constructor arguments, build it the way the existing
tests in this file already do — copy their fixture rather than inventing one.

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_gui2_window.py -k reveal -q`
Expected: FAIL — the current `_reveal` reads `sys.platform` directly, so
patching `plat.reveal_command` changes nothing and the Linux case still tries
to spawn `explorer` on Windows.

- [ ] **Step 3: Write the implementation**

Replace `_reveal` at `gerber2rml/gui2/window.py:1623`:

```python
    def _reveal(self, path):
        path = Path(path)
        cmd = plat.reveal_command(path)
        if cmd is not None:
            try:
                subprocess.Popen(cmd)
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
```

Add to the imports at the top of `gerber2rml/gui2/window.py`:

```python
from gerber2rml import platform as plat
```

- [ ] **Step 4: Run the tests**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_gui2_window.py -q`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui2/window.py tests/test_gui2_window.py
git commit -m "gui2: ask the platform module whether a file manager can select

The QDesktopServices fallback was already the right Linux behaviour - xdg-open
opens a folder and cannot select a file inside it. What moves is the decision
about whether anything better exists, which is now one function with a test
rather than a sys.platform check at the call site."
```

---

### Task 5: The startup log lands with the workspace

**Files:**
- Modify: `gerber2rml/gui2/app.py:24-33`
- Test: `tests/test_platform.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (`gui2/app.py` cannot import Qt at this point).
- Produces: `documents_dir(home=None, platform=None) -> Path` in `platform.py`.

**The bug:** `_log_path()` computes `Path.home()/"Documents"` because it runs *before* PySide6 is imported — catching a traceback from that import is its whole job. `workspace_root()` asks Qt, which reads `XDG_DOCUMENTS_DIR`. On a Danish desktop that is `~/Dokumenter`, so the workspace goes to `~/Dokumenter/SRM-CAM` and the log to `~/SRM-CAM/gui2.log` — and the log is the thing you go looking for when the app will not start. Windows agrees with itself, so no existing test catches it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_platform.py`:

```python
def test_documents_dir_reads_the_xdg_user_dirs_file(tmp_path):
    """A Danish desktop calls it Dokumenter. Qt knows that because it reads
    user-dirs.dirs; _log_path cannot ask Qt, so it reads the same file."""
    cfg = tmp_path / ".config"
    cfg.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        '# generated\nXDG_DESKTOP_DIR="$HOME/Skrivebord"\n'
        'XDG_DOCUMENTS_DIR="$HOME/Dokumenter"\n', encoding="utf-8")
    (tmp_path / "Dokumenter").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="linux") == \
        tmp_path / "Dokumenter"


def test_documents_dir_falls_back_when_there_is_no_xdg_config(tmp_path):
    (tmp_path / "Documents").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="linux") == \
        tmp_path / "Documents"


def test_documents_dir_falls_back_to_home_when_nothing_exists(tmp_path):
    assert plat.documents_dir(home=tmp_path, platform="linux") == tmp_path


def test_documents_dir_does_not_read_xdg_on_windows(tmp_path):
    """Windows has no user-dirs.dirs; Documents is Documents."""
    (tmp_path / "Documents").mkdir()
    assert plat.documents_dir(home=tmp_path, platform="win32") == \
        tmp_path / "Documents"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'documents_dir'`

- [ ] **Step 3: Write the implementation**

Append to `gerber2rml/platform.py`:

```python
def documents_dir(home=None, platform=None):
    """The user's documents folder, without asking Qt.

    ``gui2/app.py`` needs this before PySide6 is imported - catching a
    traceback from that very import is why it opens a log first - so it cannot
    use ``QStandardPaths``. But ``workspace_root()`` DOES use QStandardPaths,
    which on Linux reads ``XDG_DOCUMENTS_DIR`` from
    ``~/.config/user-dirs.dirs``. On a Danish desktop that is ``~/Dokumenter``,
    and the two would otherwise disagree: the workspace under Dokumenter and
    the startup log under ~/SRM-CAM. The log is exactly what someone goes
    looking for when the app will not start, so it has to be where they expect.

    Reads the same file Qt reads. Falls back to ``~/Documents``, then to the
    home directory itself, which is the behaviour this replaces.
    """
    home = Path.home() if home is None else Path(home)
    if not _is_windows(platform):
        cfg = home / ".config" / "user-dirs.dirs"
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line.startswith("XDG_DOCUMENTS_DIR"):
                    continue
                _, _, value = line.partition("=")
                value = value.strip().strip('"')
                if value.startswith("$HOME/"):
                    found = home / value[len("$HOME/"):]
                elif value.startswith("/"):
                    found = Path(value)
                else:
                    continue
                if found.is_dir():
                    return found
        except OSError:
            pass
    docs = home / "Documents"
    return docs if docs.is_dir() else home
```

Then replace `_log_path()` in `gerber2rml/gui2/app.py`:

```python
def _log_path():
    env = os.environ.get("SRM_CAM_HOME")
    if env:
        root = Path(env)
    else:
        from gerber2rml import platform as plat
        root = plat.documents_dir() / "SRM-CAM"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root / "gui2.log"
```

- [ ] **Step 4: Run the tests**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q && C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: `test_platform.py` 15 passed; full suite ≥880

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/platform.py gerber2rml/gui2/app.py tests/test_platform.py
git commit -m "gui2: put the startup log where the workspace actually is

_log_path computed Path.home()/'Documents' directly, and it has to: it runs
before PySide6 is imported, because catching a traceback from that import is
the reason it exists. workspace_root asks Qt, and Qt reads XDG_DOCUMENTS_DIR.

On a Danish desktop those are ~/SRM-CAM/gui2.log and ~/Dokumenter/SRM-CAM -
and the log is the thing you go looking for when the app will not start, so it
was the one in the wrong place. It reads the same user-dirs.dirs file Qt reads
now. Windows agrees with itself either way, which is why nothing caught this."
```

---

### Task 6: The machine bar says why, rather than showing dead controls

**Files:**
- Modify: `gerber2rml/gui2/machine.py:290` (`MachineBar.__init__`)
- Test: `tests/test_gui2_window.py`

**Interfaces:**
- Consumes: `capabilities(platform=None)` from Task 1.

Gating inside `MachineBar.__init__` keeps `window.py` unchanged — the window builds the bar the same way on both platforms.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gui2_window.py`:

```python
def test_machine_bar_explains_itself_where_the_link_does_not_run(qt_app, monkeypatch):
    """Not greyed out with no reason - that is the thing this interface refuses
    to ship. It names the platform and points at the path that still works."""
    from gerber2rml.gui2 import machine
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=False))
    bar = machine.MachineBar(machine.MachineLink())
    text = " ".join(w.text() for w in bar.findChildren(QLabel))
    assert "Windows" in text
    assert "height map" in text.lower()
    assert not hasattr(bar, "connect_btn")


def test_machine_bar_is_unchanged_where_the_link_does_run(qt_app, monkeypatch):
    from gerber2rml.gui2 import machine
    from gerber2rml import platform as plat
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))
    bar = machine.MachineBar(machine.MachineLink())
    assert hasattr(bar, "connect_btn")
    assert hasattr(bar, "port_combo")
```

Ensure `QLabel` is imported in the test module (it may already be).

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_gui2_window.py -k machine_bar -q`
Expected: FAIL — `connect_btn` exists in both cases

- [ ] **Step 3: Write the implementation**

In `gerber2rml/gui2/machine.py`, add to the imports:

```python
from gerber2rml import platform as plat
```

Insert immediately after `h.setSpacing(theme.GAP_M)` in `MachineBar.__init__`, before the `# -- link state --` block:

```python
        # Where the link does not run, the bar says so and stops. Not a row of
        # greyed-out controls: a dead control with no reason is exactly what
        # this interface refuses to ship, and the honest sentence is short.
        #
        # Levelling is not lost with it. A height map is a file - the Level
        # page loads a probe grid from CSV and exports through it identically -
        # so the flow is "probe once on the CNC PC, carry the CSV", which is
        # worth saying here because nobody would guess it.
        if not plat.capabilities().machine_link:
            note = QLabel(
                "The machine link runs on Windows only, so there is no "
                "Connect here. Prepare the job, export, and send the files "
                "from VPanel on the CNC PC \u2014 or load a height map "
                "measured there to export levelled toolpaths.")
            note.setWordWrap(False)
            note.setObjectName("muted")
            h.addWidget(note)
            h.addStretch(1)
            return
```

Confirm `QLabel` is among the `PySide6.QtWidgets` imports at the top of `machine.py`; add it if not.

- [ ] **Step 4: Run the tests**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_gui2_window.py -q && C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: PASS; full suite ≥880

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/gui2/machine.py tests/test_gui2_window.py
git commit -m "gui2: on a platform without the link, say so and say what to do

Not a row of greyed-out controls. A dead control with no reason is the thing
this interface refuses to ship, and the sentence that replaces it is shorter
than the controls were.

It names the workflow that still works, because nobody would guess it: a
height map is a file, the Level page already loads a probe grid from CSV and
exports through it identically, so measuring on the CNC PC and carrying the
CSV loses nothing but the measuring. Gated inside MachineBar so window.py
builds it the same way on both platforms."
```

---

### Task 7: `flash_firmware.py` finds its tools on Linux

**Files:**
- Modify: `gerber2rml/platform.py`, `scripts/flash_firmware.py:42` and `user_library_dir()`
- Test: `tests/test_platform.py`

**Interfaces:**
- Produces: `arduino_cli_candidates(platform=None, env=None, home=None) -> list[Path]`; `arduino_library_dir(platform=None, home=None) -> Path`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_platform.py`:

```python
def test_arduino_cli_candidates_point_into_the_ide_on_windows(tmp_path):
    got = plat.arduino_cli_candidates(
        "win32", env={"LOCALAPPDATA": r"C:\Users\x\AppData\Local"},
        home=tmp_path)
    assert any("arduino-cli.exe" in str(p) for p in got)


def test_arduino_cli_candidates_cover_the_linux_ide_layouts(tmp_path):
    got = [str(p) for p in plat.arduino_cli_candidates("linux", env={},
                                                       home=tmp_path)]
    assert any(p.startswith("/opt/") for p in got)
    assert any(str(tmp_path) in p for p in got)
    assert not any(p.endswith(".exe") for p in got)


def test_arduino_library_dir_differs_by_platform(tmp_path):
    assert plat.arduino_library_dir("win32", home=tmp_path) == \
        tmp_path / "Documents" / "Arduino" / "libraries"
    assert plat.arduino_library_dir("linux", home=tmp_path) == \
        tmp_path / "Arduino" / "libraries"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: FAIL — no `arduino_cli_candidates`

- [ ] **Step 3: Write the implementation**

Append to `gerber2rml/platform.py`:

```python
_IDE_TAIL = Path("resources") / "app" / "lib" / "backend" / "resources"


def arduino_cli_candidates(platform=None, env=None, home=None):
    """Where a bundled ``arduino-cli`` might live, most likely first.

    The Arduino IDE ships one inside its own resources; using it means no
    separate toolchain install and the same core versions the IDE would have
    used. Callers fall back to ``shutil.which`` when none of these exist.
    """
    import os
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if _is_windows(platform):
        local = env.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return [base / "Programs" / "Arduino IDE" / _IDE_TAIL / "arduino-cli.exe"]
    if _plat(platform) == MACOS:
        return [Path("/Applications/Arduino IDE.app/Contents") / _IDE_TAIL
                / "arduino-cli"]
    return [
        Path("/opt/arduino-ide") / _IDE_TAIL / "arduino-cli",
        Path("/usr/lib/arduino-ide") / _IDE_TAIL / "arduino-cli",
        home / ".local" / "share" / "arduino-ide" / _IDE_TAIL / "arduino-cli",
    ]


def arduino_library_dir(platform=None, home=None):
    """Where the Arduino IDE looks for user libraries.

    ``Documents/Arduino/libraries`` on Windows; plain ``~/Arduino/libraries``
    on Linux, where the IDE does not put its sketchbook under Documents.
    """
    home = Path.home() if home is None else Path(home)
    if _is_windows(platform):
        return home / "Documents" / "Arduino" / "libraries"
    return home / "Arduino" / "libraries"
```

Then in `scripts/flash_firmware.py`, delete the `_BUNDLED` constant at line 42 and rewrite the two functions:

```python
from gerber2rml import platform as plat  # noqa: E402  (after the sys.path insert)


def find_cli(explicit=None):
    if explicit:
        return Path(explicit)
    for candidate in plat.arduino_cli_candidates():
        if candidate.is_file():
            return candidate
    found = shutil.which("arduino-cli")
    if found:
        return Path(found)
    raise SystemExit(
        "arduino-cli not found. Install the Arduino IDE (it bundles one) or "
        "pass --cli with a path.")


def user_library_dir():
    """Where the IDE looks for libraries."""
    return plat.arduino_library_dir()
```

- [ ] **Step 4: Run the tests**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q && C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: `test_platform.py` 18 passed; full suite ≥880

- [ ] **Step 5: Commit**

```bash
git add gerber2rml/platform.py scripts/flash_firmware.py tests/test_platform.py
git commit -m "scripts: find arduino-cli and the sketchbook on Linux too

The bundled-CLI path was a single LOCALAPPDATA constant, and the library
directory assumed Documents/Arduino - which is a Windows layout. The IDE on
Linux keeps its sketchbook at ~/Arduino and its resources under /opt or
/usr/lib depending on how it was installed, so the lookup is a list now and
the shutil.which fallback still catches a CLI installed on its own.

A developer script rather than a shipped feature, so this gets working paths
and no further guarantees."
```

---

### Task 8: The guard test

**Files:**
- Test: `tests/test_platform.py`

This runs last of the code tasks because it fails until Tasks 3–7 land.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_platform.py`:

```python
PKG = Path(__file__).parent.parent / "gerber2rml"

# kicadplugin.config_roots predates platform.py, already takes an injectable
# platform argument, and already has the Linux branch. It is the pattern this
# module copied rather than a violation of it.
_ALLOWED = {"platform.py", "kicadplugin.py"}


def test_no_bare_platform_checks_outside_the_platform_module():
    """Same discipline as test_gui2_theme's no-hex-literals rule, for the same
    reason: a difference spelled out at the call site is one nobody can find."""
    offenders = []
    for f in sorted(PKG.rglob("*.py")):
        if f.name in _ALLOWED:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if "sys.platform" in line or "platform.system()" in line:
                offenders.append(f"{f.relative_to(PKG)}:{i}  {line.strip()[:70]}")
    assert not offenders, (
        "platform checks outside gerber2rml/platform.py - add a named "
        "function there instead:\n  " + "\n  ".join(offenders))


def test_platform_module_imports_no_qt_and_no_third_party():
    """gui2/app.py imports this before PySide6, because surviving that import
    is what it is for. A Qt import here would defeat the whole arrangement."""
    src = (PKG / "platform.py").read_text(encoding="utf-8")
    for banned in ("PySide6", "serial", "shapely", "gerbonara", "numpy"):
        assert banned not in src, banned
```

- [ ] **Step 2: Run it**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_platform.py -q`
Expected: PASS if Tasks 3–7 are complete. If it fails, it is listing real remaining call sites — fix each by routing through `platform.py`, then re-run.

- [ ] **Step 3: Run the whole suite**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: ≥880 passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_platform.py
git commit -m "tests: fail if a platform check grows back outside platform.py

The same rule test_gui2_theme applies to colour, for the same reason. COM5
reached eight call sites because nothing was watching, and the module only
helps for as long as it stays the only place that knows.

kicadplugin is named as the one exception: config_roots predates this, already
takes an injectable platform and already has the Linux branch - it is the
pattern platform.py copied, not a violation of it."
```

---

### Task 9: The PyInstaller spec builds on both, plus the desktop entry

**Files:**
- Modify: `packaging/srm-cam.spec`
- Create: `packaging/srm-cam.desktop`

**Note:** this changes the Windows build path, so the check is that the Windows build still produces the same thing — not merely that the file parses.

- [ ] **Step 1: Make the spec platform-aware**

In `packaging/srm-cam.spec`, add near the imports:

```python
import sys
```

and replace the `icon=` line in the `EXE(...)` call:

```python
    # PyInstaller only consumes an icon on Windows and macOS; on Linux the
    # AppImage takes its icon from the .desktop entry instead. Passing a .ico
    # there is ignored with a warning, and a spec should not ask for something
    # it knows is meaningless.
    icon=(str(ROOT / "packaging" / "srm-cam.ico")
          if sys.platform.startswith("win") else None),
```

`name="SRM-CAM"` needs no change — PyInstaller appends `.exe` on Windows and nothing on Linux, which is correct on both.

- [ ] **Step 2: Create the desktop entry**

Create `packaging/srm-cam.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=SRM-CAM
GenericName=PCB CAM for the Roland SRM-20
Comment=Turn Gerber and Excellon files into toolpaths for the SRM-20 mill
Exec=SRM-CAM
Icon=srm-cam
Terminal=false
Categories=Development;Engineering;Electronics;
Keywords=PCB;CAM;Gerber;CNC;milling;KiCad;
```

`Icon=srm-cam` is a name, not a path: linuxdeploy installs `srm-cam-256.png` under that name inside the AppImage.

- [ ] **Step 3: Verify the Windows build path is unchanged**

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -c "import ast,sys; ast.parse(open('packaging/srm-cam.spec').read()); print('spec parses')"`
Expected: `spec parses`

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q`
Expected: ≥880 passed

- [ ] **Step 4: Commit**

```bash
git add packaging/srm-cam.spec packaging/srm-cam.desktop
git commit -m "packaging: one spec that builds on both, and a desktop entry

PyInstaller only consumes an icon on Windows and macOS - on Linux it is
ignored with a warning, and the AppImage takes its icon from the .desktop
entry instead. The spec should not ask for something it knows is meaningless.

Everything else in the spec was already portable: the datas list, the hidden
imports, and the excludes that keep a second Qt binding out of the bundle.
name='SRM-CAM' needs no branch either - PyInstaller appends .exe on Windows
and nothing on Linux, which is right on both."
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`, `docs/usage.md`

- [ ] **Step 1: Add a Linux section to `README.md`**

Under the existing install instructions:

```markdown
### Linux (Fedora, Ubuntu)

Download `SRM-CAM-x86_64.AppImage` from the
[latest release](https://github.com/MadsRudolph/srm-cam/releases/latest), then:

```bash
chmod +x SRM-CAM-x86_64.AppImage
./SRM-CAM-x86_64.AppImage
```

No install step and no root. It carries its own Qt, so it does not care which
version your distribution ships.

**What Linux does not do:** the machine link — Connect, the DRO, jogging and
bed probing over the Arduino — is Windows-only. Prepare the job on Linux,
export, and send the files from VPanel on the CNC PC.

That costs less than it sounds, because a height map is a file. Probe the bed
once on the CNC PC, export the grid as CSV, and load it on Linux to export
levelled toolpaths exactly as if you had measured them there.
```

- [ ] **Step 2: Add the same to `docs/usage.md`**

Add this subsection immediately after the existing install/first-run section:

```markdown
## Running on Linux

The Linux build is an AppImage — one file, `chmod +x`, run. See the README for
the download link. It carries its own Qt, so the distribution's version does
not matter, and it needs no root.

Everything that turns Gerbers into toolpaths works exactly as it does on
Windows: load, check, place, level, export. The run plan, the shorts check and
the double-sided flow are all the same code and produce the same files.

**The machine link is Windows-only.** No Connect, no DRO, no jogging, no
probing the bed over the Arduino. This is deliberate: the CNC PC is Windows,
that link has only ever been run there, and an unverified motion path is not
something to hand someone standing next to a spinning tool.

### Levelling a board you prepared on Linux

A height map is a file, so you do not lose levelling — only measuring.

1. On the CNC PC, probe the bed as usual and use **Save height map…** to write
   the grid as CSV.
2. Keep that CSV with the board's session files.
3. On Linux, open the Level page and use **Load height map…**. Export as
   normal: the toolpaths are warped through the loaded grid exactly as if you
   had probed them on this machine.

A bed does not move between sessions, so one probe run serves every job on that
sheet.
```

Check the exact button labels against `gerber2rml/gui/app.py` before
committing — if they read differently in the UI, use the UI's words.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/usage.md
git commit -m "docs: how to run it on Fedora and Ubuntu, and what is missing

Says plainly that the machine link is Windows-only rather than letting someone
discover it with a board plugged in, and says what to do instead - probe once
on the CNC PC and carry the CSV, which loses the measuring and nothing else."
```

---

# Part B — requires a Linux host

Do these on the Fedora machine. Push Part A first.

### Task 11: `requirements-lock-linux.txt`

**Files:**
- Create: `packaging/requirements-lock-linux.txt`

**This cannot be produced on Windows.** `pip freeze` resolves for the platform it runs on; the existing lock pins `pywin32-ctypes` under a "pyinstaller / windows" heading and is missing the transitives PyInstaller needs on Linux.

- [ ] **Step 1: Build the environment from the loose set**

```bash
cd ~/srm-cam
python3 -m venv .build-venv
.build-venv/bin/python -m pip install --upgrade pip
.build-venv/bin/python -m pip install -r packaging/requirements-build.txt
```

- [ ] **Step 2: Freeze it**

```bash
.build-venv/bin/python -m pip freeze > packaging/requirements-lock-linux.txt
```

- [ ] **Step 3: Add the header and strip dev-only lines**

Prepend the same explanatory header the Windows lock carries, adapted:

```
# PINNED build environment for the SRM-CAM AppImage - the exact package set
# that produced the shipped Linux build. packaging/build.sh and the Linux half
# of the build workflow install from THIS file.
#
# Two locks, not one file with environment markers: the Windows lock's header
# promises that a rebuild in five years produces the same app, and a
# marker-based file is only ever resolved on one platform at a time. Two files
# keep that promise on both. The cost is that upgrading a dependency means
# regenerating both.
#
# To regenerate:
#   1. python3 -m venv .build-venv && .build-venv/bin/pip install -r packaging/requirements-build.txt
#   2. .build-venv/bin/pip freeze > packaging/requirements-lock-linux.txt
#   3. re-add this header, strip the dev-only lines (pytest, pluggy, iniconfig)
#   4. run pytest and cut a test board before committing.
#
# Python: CPython 3.12 - matched to the Windows lock so both artifacts are
# built by the same interpreter series.
```

Then delete any `pytest`, `pluggy`, `iniconfig`, `Pygments` lines.

- [ ] **Step 4: Verify the suite runs against it**

```bash
.build-venv/bin/python -m pip install -e . --no-deps
.build-venv/bin/python -m pip install pytest
QT_QPA_PLATFORM=offscreen QT_OPENGL=software .build-venv/bin/python -m pytest -q
```
Expected: ≥880 passed. **This is the first proof the suite runs on Linux at all.**

- [ ] **Step 5: Commit**

```bash
git add packaging/requirements-lock-linux.txt
git commit -m "packaging: pin the Linux build environment

The Windows lock cannot serve: it pins pywin32-ctypes under a 'pyinstaller /
windows' heading and is missing what PyInstaller pulls in on Linux.

Two files rather than one with environment markers, because the Windows lock's
header promises a rebuild in five years produces the same app, and a
marker-based file is only ever resolved on one platform at a time. Two locks
keep that promise on both; the cost is regenerating both when a dependency
moves, which each header now says."
```

---

### Task 12: `packaging/build.sh`

**Files:**
- Create: `packaging/build.sh` (mode 755)

Mirrors `build.ps1` stage for stage so the two are comparable when one breaks. Same switches, spelled the POSIX way.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Build SRM-CAM into a Linux AppImage.
#
# Two stages, mirroring packaging/build.ps1 so the two are comparable when one
# of them breaks:
#   1. PyInstaller -> dist/SRM-CAM/                    (the runnable app folder)
#   2. linuxdeploy -> dist_installer/*.AppImage        (the downloadable file)
#
# Usage: packaging/build.sh [--recreate] [--loose] [--skip-installer]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.build-venv"
PY="$VENV/bin/python"
RECREATE=0; LOOSE=0; SKIP=0
for arg in "$@"; do
  case "$arg" in
    --recreate) RECREATE=1 ;;
    --loose) LOOSE=1 ;;
    --skip-installer) SKIP=1 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

echo "== SRM-CAM build =="
echo "repo root : $ROOT"

[ "$RECREATE" = 1 ] && rm -rf "$VENV"
if [ ! -x "$PY" ]; then
  echo "Creating build venv at $VENV ..."
  python3 -m venv "$VENV"
  "$PY" -m pip install --upgrade pip
  # Pinned by default: a release build must be reproducible. --loose is the
  # opt-in path for deliberately upgrading a dependency (then re-freeze).
  REQS="packaging/requirements-lock-linux.txt"
  [ "$LOOSE" = 1 ] && REQS="packaging/requirements-build.txt"
  echo "deps      : $REQS"
  "$PY" -m pip install -r "$REQS"
fi
echo "python    : $PY"

echo
echo "[1/2] PyInstaller..."
"$PY" -m PyInstaller --noconfirm packaging/srm-cam.spec
APP="$ROOT/dist/SRM-CAM/SRM-CAM"
[ -x "$APP" ] || { echo "Expected app missing: $APP" >&2; exit 1; }
echo "  -> $APP"

[ "$SKIP" = 1 ] && { echo; echo "Done (app folder only)."; exit 0; }

echo
echo "[2/2] AppImage..."
command -v linuxdeploy-x86_64.AppImage >/dev/null || {
  echo "linuxdeploy not found. Get it with:" >&2
  echo "  wget https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" >&2
  echo "  chmod +x linuxdeploy-x86_64.AppImage && sudo mv it onto your PATH" >&2
  exit 2
}

VERSION="$("$PY" -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")"
APPDIR="$ROOT/dist/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$ROOT/dist/SRM-CAM/." "$APPDIR/usr/bin/"

mkdir -p "$ROOT/dist_installer"
OUTPUT="SRM-CAM-$VERSION-x86_64.AppImage" \
VERSION="$VERSION" \
linuxdeploy-x86_64.AppImage \
  --appdir "$APPDIR" \
  --executable "$APPDIR/usr/bin/SRM-CAM" \
  --desktop-file "$ROOT/packaging/srm-cam.desktop" \
  --icon-file "$ROOT/packaging/srm-cam-256.png" \
  --output appimage
mv "SRM-CAM-$VERSION-x86_64.AppImage" dist_installer/

# Also drop a version-less copy. The DTU guide links to
# releases/latest/download/<name>, which only resolves if every release ships
# an asset with this exact un-versioned name - same arrangement as build.ps1
# makes for SRM-CAM-Setup.exe.
cp "dist_installer/SRM-CAM-$VERSION-x86_64.AppImage" \
   "dist_installer/SRM-CAM-x86_64.AppImage"

echo
echo "Done -> dist_installer/SRM-CAM-$VERSION-x86_64.AppImage"
echo "      + dist_installer/SRM-CAM-x86_64.AppImage  (version-less)"
```

- [ ] **Step 2: Make it executable and run it**

```bash
chmod +x packaging/build.sh
git update-index --chmod=+x packaging/build.sh
packaging/build.sh
```
Expected: an AppImage in `dist_installer/`, >50 MB.

- [ ] **Step 3: Run the AppImage — the acceptance test**

```bash
./dist_installer/SRM-CAM-x86_64.AppImage
```

Confirm the window appears, load `examples/preload_example`, and check the machine bar shows the Windows-only sentence from Task 6. **Check the 3D view specifically** — pyqtgraph over PyOpenGL is where a Wayland/XWayland difference would show up first, and nobody has looked. If it fails, try `QT_QPA_PLATFORM=xcb ./dist_installer/SRM-CAM-x86_64.AppImage` and record which worked.

- [ ] **Step 4: Commit**

```bash
git add packaging/build.sh
git commit -m "packaging: build the Linux AppImage

Mirrors build.ps1 stage for stage - same switches, same pinned-by-default
policy, same version-less copy so releases/latest/download/<name> keeps
resolving - so that when one of the two breaks the other is a straight
comparison rather than a different program."
```

---

### Task 13: CI on both platforms

**Files:**
- Modify: `.github/workflows/tests.yml`, `.github/workflows/build.yml`

- [ ] **Step 1: Matrix the gating test job**

In `tests.yml`, change the `locked` job:

```yaml
  locked:
    # The gating job: exactly what we ship, on both platforms we ship to.
    if: github.event_name != 'schedule'
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            lock: packaging/requirements-lock.txt
          - os: ubuntu-latest
            lock: packaging/requirements-lock-linux.txt
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: ${{ matrix.lock }}

      - name: Install pinned dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r ${{ matrix.lock }}
          python -m pip install pytest==9.1.1
          python -m pip install -e . --no-deps

      - name: Check version consistency
        run: python scripts/check_version.py

      - name: Run tests
        run: python -m pytest -q
```

Give `canary` the same `matrix: os: [windows-latest, ubuntu-latest]` — it installs unpinned, so it needs no lock input.

**Do not add a speculative `apt-get`.** Run it first and add only what the failure actually names. `offscreen` avoids the X11 platform plugin and so avoids most of it; if Qt still fails to load, the error is loud and specific and tells you the missing library. A pre-emptive install of a dozen `libxcb-*` packages is how this step becomes cargo-cult and stays that way.

- [ ] **Step 2: Add the AppImage job to `build.yml`**

Append a second job. It **must** `needs: installer` — the Windows job creates the draft release, and two jobs racing on `gh release create` would fail:

```yaml
  appimage:
    needs: installer          # the Windows job creates the release; this adds to it
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Check version consistency (and that it matches the tag)
        run: |
          if [ "${{ github.ref_type }}" = "tag" ]; then
            python scripts/check_version.py "${{ github.ref_name }}"
          else
            python scripts/check_version.py
          fi

      - name: Install linuxdeploy
        run: |
          wget -q https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
          chmod +x linuxdeploy-x86_64.AppImage
          sudo mv linuxdeploy-x86_64.AppImage /usr/local/bin/

      - name: Build
        run: packaging/build.sh

      - name: Verify the AppImage was produced
        run: |
          f=$(ls -S dist_installer/SRM-CAM-*-x86_64.AppImage | head -1)
          [ -n "$f" ] || { echo "No AppImage in dist_installer/"; exit 1; }
          size=$(( $(stat -c%s "$f") / 1024 / 1024 ))
          [ "$size" -ge 50 ] || { echo "AppImage is only ${size} MB - the Qt payload is probably missing"; exit 1; }
          echo "Built $(basename "$f") - ${size} MB"

      - name: Checksums
        run: |
          cd dist_installer
          sha256sum SRM-CAM-*.AppImage > SHA256SUMS-linux.txt
          cat SHA256SUMS-linux.txt

      - uses: actions/upload-artifact@v4
        with:
          name: SRM-CAM-appimage
          path: |
            dist_installer/SRM-CAM-*.AppImage
            dist_installer/SHA256SUMS-linux.txt
          retention-days: 90

      - name: Attach to the draft release
        if: github.ref_type == 'tag'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release upload "${{ github.ref_name }}" \
            dist_installer/SRM-CAM-*.AppImage \
            dist_installer/SHA256SUMS-linux.txt --clobber
```

- [ ] **Step 3: Verify by dispatch**

Push, then run the build workflow manually (Actions → build installer → Run workflow) and confirm both jobs go green and both artifacts appear.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/tests.yml .github/workflows/build.yml
git commit -m "ci: test on Linux, and build the AppImage there

The gating job is a matrix now, each platform against its own lock, because
'the app we ship is broken' has been a question about two apps since the
AppImage existed.

The AppImage job needs the Windows one rather than running beside it: the
Windows job creates the draft release and two jobs racing on gh release create
would fail, so this one uploads into what that already made."
```

---

### Task 14: Update the version-consistency check

**Files:**
- Modify: `scripts/check_version.py` — only if Task 12 introduced a version string outside the three files it already knows about.

- [ ] **Step 1: Confirm whether it is needed**

`build.sh` reads the version from `pyproject.toml` at build time and `srm-cam.desktop` carries no version, so no fourth source of truth exists and this task is likely a no-op.

Run: `C:/Users/Mads2/AppData/Local/Programs/Python/Python313/python.exe scripts/check_version.py`
Expected: passes unchanged.

- [ ] **Step 2: If it passed, close the task with no change.** Otherwise add the new file to the three it checks, following the existing structure in that script.

---

## Done when

- [ ] `python -m pytest -q` ≥880 passed on Windows
- [ ] `python -m pytest -q` ≥880 passed on Fedora
- [ ] Both CI jobs green
- [ ] `SRM-CAM-x86_64.AppImage` launches on Fedora, loads the demo board, draws it, and the machine bar explains itself
- [ ] The Windows installer still builds and is unchanged in behaviour
- [ ] The Wayland/3D-view question in §10 of the spec has an answer recorded in the doc
