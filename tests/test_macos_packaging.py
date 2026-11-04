"""The macOS build, as far as a machine that is not a Mac can check it.

The spec's macOS branch is run for real with PyInstaller's build classes
replaced by recorders, so what it would hand to BUNDLE is checked here without
hdiutil. Whether the result opens on a Mac is the CI dmg job's question, and a
person's: see packaging/README.md.
"""
import struct
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def _run_spec(platform, monkeypatch):
    """Execute srm-cam.spec as PyInstaller would, recording what it builds."""
    built = {}

    def recorder(name):
        def make(*args, **kw):
            built[name] = {"args": args, "kw": kw}
            return name
        return make

    env = {"SPECPATH": str(PACKAGING), "__file__": str(PACKAGING / "srm-cam.spec")}
    for name in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE"):
        env[name] = recorder(name)
    env["Analysis"] = lambda *a, **k: type("A", (), {
        "pure": [], "scripts": [], "binaries": [], "datas": []})()
    hooks = type(sys)("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: []
    hooks.collect_data_files = lambda name: []
    monkeypatch.setitem(sys.modules, "PyInstaller", type(sys)("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils",
                        type(sys)("PyInstaller.utils"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setattr(sys, "platform", platform)
    exec(compile((PACKAGING / "srm-cam.spec").read_text(encoding="utf-8"),
                 "srm-cam.spec", "exec"), env)
    return built


def test_the_spec_makes_an_app_bundle_on_macos(monkeypatch):
    built = _run_spec("darwin", monkeypatch)
    kw = built["BUNDLE"]["kw"]
    assert kw["name"] == "SRM-CAM.app"
    assert kw["icon"].endswith("srm-cam.icns") and Path(kw["icon"]).is_file()
    assert kw["bundle_identifier"]
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]["version"]
    assert kw["version"] == version
    assert kw["info_plist"]["NSHighResolutionCapable"] is True
    assert built["EXE"]["kw"]["console"] is False


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_the_spec_makes_no_bundle_anywhere_else(platform, monkeypatch):
    built = _run_spec(platform, monkeypatch)
    assert "BUNDLE" not in built and "COLLECT" in built


def test_the_windows_icon_is_still_only_for_windows(monkeypatch):
    assert _run_spec("linux", monkeypatch)["EXE"]["kw"]["icon"] is None
    assert _run_spec("win32", monkeypatch)["EXE"]["kw"]["icon"].endswith(".ico")


def test_the_minimum_macos_matches_what_the_pinned_numpy_can_load(monkeypatch):
    """numpy 2.5.2's macOS wheels are tagged macosx_14_0. The Finder should be
    the one to say so, not a crash at startup."""
    lock = (PACKAGING / "requirements-lock-macos.txt").read_text(encoding="utf-8")
    assert "numpy==2.5.2" in lock, "new numpy: check its wheel tag, then this"
    plist = _run_spec("darwin", monkeypatch)["BUNDLE"]["kw"]["info_plist"]
    assert plist["LSMinimumSystemVersion"] == "14.0"


def test_the_icns_is_well_formed():
    data = (PACKAGING / "srm-cam.icns").read_bytes()
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    pos, kinds = 8, []
    while pos < len(data):
        kind, size = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        assert data[pos + 8:pos + 16] == b"\x89PNG\r\n\x1a\n"
        kinds.append(kind)
        pos += size
    assert pos == len(data)
    assert b"ic08" in kinds and b"ic10" in kinds


def test_the_macos_lock_is_the_linux_lock_plus_macholib():
    def pins(name):
        return {ln for ln in (PACKAGING / name).read_text(encoding="utf-8").splitlines()
                if "==" in ln and not ln.startswith("#")}
    extra = pins("requirements-lock-macos.txt") - pins("requirements-lock-linux.txt")
    assert {p.split("==")[0] for p in extra} == {"macholib"}
    assert not pins("requirements-lock-linux.txt") - pins("requirements-lock-macos.txt")


def test_the_build_script_makes_a_drag_target_and_refuses_other_systems():
    text = (PACKAGING / "build_macos.sh").read_text(encoding="utf-8")
    assert "ln -s /Applications" in text
    assert "hdiutil create" in text
    assert 'uname -s)" != "Darwin"' in text
    assert "requirements-lock-macos.txt" in text
    assert (PACKAGING / "build_macos.sh").stat().st_mode & 0o100


def test_ci_builds_both_architectures_on_mac_runners():
    text = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    assert "packaging/build_macos.sh" in text
    assert "runner: macos-15\n" in text and "arch: arm64" in text
    assert "runner: macos-15-intel" in text and "arch: x86_64" in text
