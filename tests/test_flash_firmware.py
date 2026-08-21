"""The library-sync step of scripts/flash_firmware.py.

This is the part with real consequences: the sketch resolves
``<SRM20SPIRemote.h>`` from the user's Arduino libraries folder, not from the
repo, so a stale copy there produces a firmware that compiles cleanly and is
silently missing features. Sync has to be correct and idempotent.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "flash_firmware", ROOT / "scripts" / "flash_firmware.py")
flash = importlib.util.module_from_spec(_spec)
sys.modules["flash_firmware"] = flash
_spec.loader.exec_module(flash)


@pytest.fixture
def fake_repo_library(tmp_path, monkeypatch):
    """A stand-in repo library + an empty user library dir."""
    src = tmp_path / "repo" / "SRM20SPIRemote"
    src.mkdir(parents=True)
    (src / "SRM20SPIRemote.h").write_text("#define SRM20SPIREMOTE_LOCAL_PATCH 1\n")
    (src / "SRM20SPIRemote.cpp").write_text("// patched\n")
    (src / "examples").mkdir()
    (src / "examples" / "demo.ino").write_text("void setup(){}\n")
    userlib = tmp_path / "user" / "libraries"
    userlib.mkdir(parents=True)
    monkeypatch.setattr(flash, "LIBRARY", src)
    monkeypatch.setattr(flash, "user_library_dir", lambda: userlib)
    return src, userlib / "SRM20SPIRemote"


def test_installs_when_missing(fake_repo_library):
    src, dest = fake_repo_library
    msg = flash.sync_library()
    assert "installed" in msg
    assert (dest / "SRM20SPIRemote.h").read_text() == \
           (src / "SRM20SPIRemote.h").read_text()
    assert (dest / "examples" / "demo.ino").exists()      # subdirs come too


def test_updates_a_stale_copy(fake_repo_library):
    """The exact trap this script exists for: an unpatched library sitting in
    the user's folder, which the IDE would silently build against."""
    src, dest = fake_repo_library
    dest.mkdir(parents=True)
    (dest / "SRM20SPIRemote.h").write_text("// old unpatched vendor copy\n")
    (dest / "SRM20SPIRemote.cpp").write_text("// patched\n")   # this one matches
    msg = flash.sync_library()
    assert "updated" in msg and "SRM20SPIRemote.h" in msg
    assert "LOCAL_PATCH" in (dest / "SRM20SPIRemote.h").read_text()


def test_is_idempotent(fake_repo_library):
    flash.sync_library()
    assert "already in sync" in flash.sync_library()


def test_dry_run_changes_nothing(fake_repo_library):
    _src, dest = fake_repo_library
    msg = flash.sync_library(dry_run=True)
    assert "would install" in msg
    assert not dest.exists()


def test_real_repo_library_is_actually_patched():
    """Guards the whole point: if the repo's copy ever loses the patch marker,
    'I' and 'F' become NOPATCH stubs on every board flashed from it."""
    header = (ROOT / "hardware" / "SRM20SPIRemote" / "SRM20SPIRemote.h").read_text()
    assert "SRM20SPIREMOTE_LOCAL_PATCH" in header
    for addition in ("getCommandVersion", "rawTxRx", "setFrameDelayUs"):
        assert addition in header, addition


def test_sketch_guards_patched_calls_so_it_builds_against_upstream():
    """The sketch must still compile if someone installs a pristine library."""
    ino = (ROOT / "hardware" / "srm20_spi_probe" / "srm20_spi_probe.ino").read_text()
    assert ino.count("#ifdef SRM20SPIREMOTE_LOCAL_PATCH") == \
           ino.count("#endif") - ino.count("#ifndef")
    for guarded in ("getCommandVersion", "setFrameDelayUs", "frameDelayUs"):
        assert guarded in ino, guarded
    assert "NOPATCH" in ino          # the fallback branch exists
