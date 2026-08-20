"""The KiCad build-area plugin: finding where KiCad keeps plugins, and
installing/updating our copy there.

No KiCad and no pcbnew is involved on this side — it is file layout only, so
every case here runs against a temp directory that looks like a KiCad config
root.
"""
from gerber2rml.engine import kicadplugin


def test_finds_versioned_plugin_dirs_newest_first(tmp_path):
    """KiCad keeps one config tree per version: <root>/10.0/scripting/plugins.

    A machine can have several. We offer the newest first, and ignore the
    non-version folders KiCad also keeps there (colors/, templates/, ...).
    """
    for ver in ("9.0", "10.0", "8.0"):
        (tmp_path / ver / "scripting" / "plugins").mkdir(parents=True)
    (tmp_path / "colors").mkdir()

    found = kicadplugin.plugin_dirs(tmp_path)

    assert [p.relative_to(tmp_path).as_posix() for p in found] == [
        "10.0/scripting/plugins",
        "9.0/scripting/plugins",
        "8.0/scripting/plugins",
    ]


def _fake_source(tmp_path, version="1.0.0"):
    """A stand-in for the bundled plugin folder."""
    src = tmp_path / "src"
    (src / "srm20area" / "__pycache__").mkdir(parents=True)
    (src / "action_srm20_area.py").write_text("# action", encoding="utf-8")
    (src / "VERSION").write_text(version, encoding="utf-8")
    (src / "srm20area" / "geometry.py").write_text("BED = 1", encoding="utf-8")
    (src / "srm20area" / "__pycache__" / "geometry.pyc").write_bytes(b"junk")
    return src


def test_install_copies_the_plugin_without_pycache(tmp_path):
    """A stale .pyc shadowing a changed .py is a genuinely confusing failure,
    so the bytecode cache never travels."""
    dest = tmp_path / "plugins"
    dest.mkdir()

    kicadplugin.install(_fake_source(tmp_path), dest)

    landed = dest / kicadplugin.PLUGIN_DIRNAME
    assert (landed / "action_srm20_area.py").read_text(encoding="utf-8") == "# action"
    assert (landed / "srm20area" / "geometry.py").read_text(encoding="utf-8") == "BED = 1"
    assert not (landed / "srm20area" / "__pycache__").exists()


def test_reinstall_removes_a_file_the_new_version_dropped(tmp_path):
    """Replace, not merge: a leftover module from an older version would still
    be importable and could shadow the new one."""
    dest = tmp_path / "plugins"
    dest.mkdir()
    src = _fake_source(tmp_path)
    kicadplugin.install(src, dest)
    landed = dest / kicadplugin.PLUGIN_DIRNAME
    (landed / "srm20area" / "gone_in_v2.py").write_text("old", encoding="utf-8")

    kicadplugin.install(src, dest)

    assert not (landed / "srm20area" / "gone_in_v2.py").exists()
    assert (landed / "srm20area" / "geometry.py").exists()


def test_status_reports_missing_outdated_and_current(tmp_path):
    """What the launch-time check asks: is our plugin there, and is it ours?"""
    dest = tmp_path / "plugins"
    dest.mkdir()

    assert kicadplugin.status(dest, "1.1.0") == "missing"

    kicadplugin.install(_fake_source(tmp_path, version="1.0.0"), dest)
    assert kicadplugin.status(dest, "1.1.0") == "outdated"
    assert kicadplugin.status(dest, "1.0.0") == "current"


def test_config_root_follows_the_platform(tmp_path):
    """KiCad keeps its config somewhere different on each OS. The lab PC is
    Windows; students turn up with Macs."""
    home = tmp_path / "home"
    env = {"APPDATA": str(tmp_path / "Roaming")}

    win = kicadplugin.config_roots(platform="win32", env=env, home=home)
    mac = kicadplugin.config_roots(platform="darwin", env=env, home=home)
    lin = kicadplugin.config_roots(platform="linux", env=env, home=home)

    assert win == [tmp_path / "Roaming" / "kicad"]
    assert mac == [home / "Library" / "Preferences" / "kicad"]
    assert lin == [home / ".config" / "kicad"]


def test_config_root_falls_back_when_appdata_is_unset(tmp_path):
    """A Windows box with no APPDATA shouldn't crash the launch-time check."""
    home = tmp_path / "home"

    roots = kicadplugin.config_roots(platform="win32", env={}, home=home)

    assert roots == [home / "AppData" / "Roaming" / "kicad"]


def test_bundled_source_is_a_real_plugin_folder():
    """The folder we ship must actually be there — in a source checkout and,
    via the PyInstaller spec, inside the frozen app."""
    src = kicadplugin.bundled_source()

    assert (src / "VERSION").is_file()
    assert (src / "__init__.py").is_file()
    assert (src / "srm20area" / "geometry.py").is_file()


def test_plugin_draws_the_same_machine_the_cam_exports_for():
    """One definition of the SRM-20, two tools.

    If these ever drift, KiCad would tell a student their board fits while
    SRM-CAM refuses to cut it (or worse, the other way round).
    """
    import importlib.util
    from gerber2rml.backends import SRM20_BED

    path = kicadplugin.bundled_source() / "srm20area" / "geometry.py"
    spec = importlib.util.spec_from_file_location("_srm20area_geometry", path)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)        # pure module: must not need pcbnew

    assert (geometry.BED_X, geometry.BED_Y) == SRM20_BED


def _geometry():
    """The plugin's pure geometry module, loaded straight off disk."""
    import importlib.util
    path = kicadplugin.bundled_source() / "srm20area" / "geometry.py"
    spec = importlib.util.spec_from_file_location("_srm20area_geom", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_usable_area_leaves_room_to_hold_the_stock_down():
    """The spindle reaching a point is not the same as a board being millable
    there: the stock has to be taped or screwed down, and the cut-out pass
    drives the tool all the way around the outline."""
    geom = _geometry()

    assert geom.usable() == (geom.BED_X - 2 * geom.HOLD_DOWN_MARGIN,
                             geom.BED_Y - 2 * geom.HOLD_DOWN_MARGIN)


def test_a_board_that_fits_is_told_how_much_room_is_left():
    geom = _geometry()
    uw, uh = geom.usable()

    assert geom.room_to_grow(uw - 20, uh - 10) == (20, 10)
    assert "Fits" in geom.verdict(uw - 20, uh - 10)


def test_an_oversized_board_is_told_by_how_much_in_each_direction():
    """'Too big' on its own sends someone back to guess. The numbers say
    exactly what to change."""
    geom = _geometry()
    uw, uh = geom.usable()

    said = geom.verdict(uw + 15, uh + 4)

    assert "15 mm too wide" in said
    assert "4 mm too tall" in said


def test_the_outer_rectangle_is_the_machine_and_the_inner_one_the_board():
    geom = _geometry()

    rects = geom.rectangles()

    assert [(w, h) for w, h, _width, _label in rects] == [
        (geom.BED_X, geom.BED_Y), geom.usable()]


def test_offers_when_the_plugin_is_missing_from_an_installed_kicad(tmp_path):
    dest = tmp_path / "plugins"
    dest.mkdir()

    assert kicadplugin.should_offer([dest], "1.0.0", declined=None)


def test_says_nothing_when_kicad_is_not_installed(tmp_path):
    """No KiCad found is not a problem to report — plenty of people run
    SRM-CAM on a machine that never had it."""
    assert not kicadplugin.should_offer([], "1.0.0", declined=None)


def test_says_nothing_when_the_installed_plugin_is_current(tmp_path):
    dest = tmp_path / "plugins"
    dest.mkdir()
    kicadplugin.install(_fake_source(tmp_path, version="1.0.0"), dest)

    assert not kicadplugin.should_offer([dest], "1.0.0", declined=None)


def test_does_not_nag_after_the_user_declined_this_version(tmp_path):
    """Asked once, answered no. Asking again every launch is how a helpful
    prompt turns into something people click away without reading."""
    dest = tmp_path / "plugins"
    dest.mkdir()

    assert not kicadplugin.should_offer([dest], "1.0.0", declined="1.0.0")
    # ...but a newer version is a new question.
    assert kicadplugin.should_offer([dest], "1.1.0", declined="1.0.0")


# --- the GUI side: the menu item actually installs -------------------------

def _window():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import matplotlib
    matplotlib.use("Agg")
    from PySide6.QtWidgets import QApplication
    from gerber2rml.gui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def test_setup_menu_item_installs_into_every_kicad_version_found(tmp_path, monkeypatch):
    """A PC upgraded from KiCad 9 to 10 keeps both trees, and the student opens
    whichever shortcut is on the desktop. Install into both."""
    from PySide6.QtWidgets import QMessageBox
    from gerber2rml.engine import kicadplugin

    root = tmp_path / "kicad"
    for ver in ("9.0", "10.0"):
        (root / ver / "scripting" / "plugins").mkdir(parents=True)
    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [root])
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2]))

    _window()._on_setup_kicad_plugin()

    for ver in ("9.0", "10.0"):
        landed = root / ver / "scripting" / "plugins" / kicadplugin.PLUGIN_DIRNAME
        assert (landed / "action_srm20_area.py").is_file()
        assert (landed / "srm20area" / "geometry.py").is_file()
        assert kicadplugin.status(landed.parent, kicadplugin.bundled_version()) == "current"
    assert shown and "Installed to:" in shown[0]


def test_setup_menu_item_explains_itself_when_kicad_is_absent(tmp_path, monkeypatch):
    """Not an error — plenty of people run SRM-CAM on a PC without KiCad."""
    from PySide6.QtWidgets import QMessageBox
    from gerber2rml.engine import kicadplugin

    monkeypatch.setattr(kicadplugin, "config_roots", lambda *a, **k: [tmp_path / "nope"])
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2]))

    _window()._on_setup_kicad_plugin()

    assert shown and "No KiCad installation was found" in shown[0]
