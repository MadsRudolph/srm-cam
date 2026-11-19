"""Projects: many boards, each ticked off as it is made (2026-11-19, the
analog synth's dozen boards on the mill and the laser)."""
import json
from pathlib import Path

import pytest

from gerber2rml import project as pj

FIX = Path(__file__).parent / "fixtures"


def test_a_project_keeps_its_boards_and_ticks(tmp_path):
    p = pj.Project("synth")
    a = p.add(FIX / "mosfet_test")
    b = p.add(FIX / "curtain_drive")
    assert p.add(FIX / "mosfet_test") is a           # once
    a.steps = [("drill", "Drill", "mill"), ("laser_traces", "Traces", "laser")]
    a.done = {"drill"}
    p.save(tmp_path / "synth.srmproj")
    q = pj.load(tmp_path / "synth.srmproj")
    assert [x.name for x in q.boards] == [a.name, b.name]
    assert q.boards[0].done == {"drill"}
    assert q.boards[0].progress() == (1, 2)
    # Folders are kept relative to the project file, so it moves with them.
    data = json.loads((tmp_path / "synth.srmproj").read_text())
    assert not Path(data["boards"][0]["gerber_dir"]).is_absolute()


def test_next_unfinished_skips_the_done(tmp_path):
    p = pj.Project("x")
    a, b, c = (p.add(FIX / n) for n in ("mosfet_test", "curtain_drive",
                                         "stencil_wroom"))
    for x in (a, b, c):
        x.steps = [("s", "S", "mill")]
    b.done = {"s"}
    assert p.next_unfinished() is a
    assert p.next_unfinished(after=a) is c        # b is done
    a.done = c.done = {"s"}
    assert p.next_unfinished() is None


def test_boards_are_found_and_named_by_their_folder(tmp_path):
    for name in ("vcf", "output", "brain"):
        g = tmp_path / "hardware" / name / "production" / "gerbers"
        g.mkdir(parents=True)
        (g / f"{name}-B_Cu.gbl").write_text("x")
        (g / f"{name}-Edge_Cuts.gm1").write_text("x")
    (tmp_path / "hardware" / "brain" / "srm-cam").mkdir()
    for f in ("brain-F_Cu.gbr", "brain-Edge_Cuts.gbr"):
        (tmp_path / "hardware" / "brain" / "srm-cam" / f).write_text("x")
    (tmp_path / "hardware" / "notes").mkdir()
    found = pj.discover(tmp_path / "hardware")
    assert len(found) == 4
    assert sorted(pj.board_name(f) for f in found) == [
        "brain", "brain", "output", "vcf"]
    p = pj.Project("synth")
    names = [p.add(f).name for f in found]
    assert len(set(names)) == 4                   # the second brain renamed


# -- the window --------------------------------------------------------------

@pytest.fixture
def win(qt_app, monkeypatch, tmp_path):
    from gerber2rml import platform as plat
    from gerber2rml.gui2.window import MainWindow
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


def test_the_project_page_is_pro_only(win, monkeypatch):
    def button():
        return next(b for b, k in win.mode_switch._keys.items()
                    if k == "project")
    win._sync_tier()
    assert not button().isHidden()
    win.show_mode("project")
    assert win.mode() == "project"
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    win._sync_tier()
    assert win.mode() == "cnc" and button().isHidden()
    win.show_mode("project")
    assert win.mode() == "cnc"


def test_boards_keep_their_ticks_and_setups(win, tmp_path):
    ctl = win.project_ctl
    ctl.new(tmp_path / "synth.srmproj")
    a, b = ctl.add_folders([FIX / "mosfet_test", FIX / "curtain_drive"])
    assert ctl.open_board(a)
    assert ctl.current is a and a.steps                 # its plan's steps
    first = a.steps[0][0]
    win.traveller.set_done(first, True)                 # a run finished
    assert first in a.done
    assert ctl.open_board(b)
    assert Path(a.setup).is_file()                      # a was kept
    assert not win.traveller.is_done(first) or first not in dict(
        (k, 1) for k, _t, _m in b.steps)
    assert ctl.open_board(a)
    assert win.traveller.is_done(first)                 # as it was left
    # On disk too.
    again = pj.load(tmp_path / "synth.srmproj")
    assert first in again.boards[0].done


def test_ticks_on_the_page_reach_the_rail(win, tmp_path, qt_app):
    from PySide6.QtCore import Qt
    ctl = win.project_ctl
    ctl.new(tmp_path / "p.srmproj")
    (a,) = ctl.add_folders([FIX / "mosfet_test"])
    ctl.open_board(a)
    key = a.steps[-1][0]
    page = ctl.page
    page.refresh()
    top = page.tree.topLevelItem(0)
    child = next(top.child(i) for i in range(top.childCount())
                 if top.child(i).data(0, Qt.UserRole) == key)
    child.setCheckState(2, Qt.Checked)
    qt_app.processEvents()                  # the list refreshes after the click
    assert key in a.done and win.traveller.is_done(key)


def test_a_finished_laser_job_ticks_its_row(win, tmp_path):
    ctl = win.project_ctl
    ctl.new(tmp_path / "p.srmproj")
    (a,) = ctl.add_folders([FIX / "mosfet_test"])
    ctl.open_board(a)
    laser_keys = [k for k, _t, m in a.steps if k.startswith("laser_")]
    if not laser_keys:
        pytest.skip("this board has no laser rows")
    from types import SimpleNamespace
    from gerber2rml.gui2.stencil_laser import StencilLaserDialog
    fake = SimpleNamespace(_host=win, kind=laser_keys[0][len("laser_"):])
    StencilLaserDialog._tell_host_done(fake)
    assert laser_keys[0] in a.done


def test_opening_another_board_by_hand_lets_go(win, tmp_path):
    ctl = win.project_ctl
    ctl.new(tmp_path / "p.srmproj")
    (a,) = ctl.add_folders([FIX / "mosfet_test"])
    ctl.open_board(a)
    win.load_folder(str(FIX / "curtain_drive"))
    assert ctl.current is None
