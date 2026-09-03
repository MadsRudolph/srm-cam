"""Things the first interface did that the second did not - now ported.

Each of these came out of auditing gui1 against gui2 before gui1 is deleted.
They are the ones that matter with a hand on the machine: a key the
tooltips promised, a pre-flight check that could never fire, and a rework
file that was written for the wrong board.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.load_folder(str(FIXT))
    yield w
    w.close()


def _tilted_map():
    """A sloped sheet: every point on one plane, so the warp is unmistakable."""
    return [[f"{x:.3f}", f"{y:.3f}", f"{0.01 * x:.4f}"]
            for y in (5.0, 40.0, 75.0) for x in (5.0, 60.0, 115.0)]


def _zs_below_zero(path):
    text = Path(path).read_text(encoding="utf-8")
    return {round(float(v), 3) for v in re.findall(r"Z(-?\d+\.?\d*)", text)
            if float(v) < 0}


# ------------------------------------------------------------ the Z keys
def test_page_up_and_down_nudge_z_as_the_tooltips_promise(loaded):
    """Both Z buttons' tooltips said the keys did the same. Nothing was
    bound, which is a tooltip lying about a machine control."""
    jogs = []
    loaded.bar._jog = lambda d: jogs.append(d)
    acts = {k: [a for a in loaded.findChildren(QAction)
                if a.shortcut() == QKeySequence(k)]
            for k in (Qt.Key_PageUp, Qt.Key_PageDown)}
    assert all(len(v) == 1 for v in acts.values()), acts
    acts[Qt.Key_PageUp][0].trigger()
    acts[Qt.Key_PageDown][0].trigger()
    assert jogs == [+1, -1]


# ------------------------------------------------------- the Z-reach check
def test_the_link_remembers_where_the_copper_is(qt_app):
    from gerber2rml.gui2.machine import MachineLink
    link = MachineLink()
    link._ser = object()                             # "connected"
    link.submit("zero_z", lambda _s: (1.0, 2.0, -21.5))
    link.submit("touch", lambda _s: None)            # a miss changes nothing
    link._q.put(None)
    link._run()                                      # drain, on this thread
    assert link.surface_z == -21.5
    link.disconnect_from("test")
    assert link.surface_z is None


def test_a_touch_off_answers_the_z_reach_check(loaded):
    """The pre-flight never received the probed surface, so its Z-reach
    check was permanently 'unknown' - it could not fail a job that would run
    out of Z stroke."""
    def titles():
        return [c.title for c in loaded._checks]
    assert any(t.startswith("Z reach unknown") for t in titles())
    loaded.link.surface_z = -20.0
    loaded._on_op_done("zero_z", (0.0, 0.0, -20.0))
    assert "Z reach OK" in titles()
    loaded.link.surface_z = -59.5                    # right on the floor
    loaded._on_op_done("touch", (0.0, 0.0, -59.5))
    assert any(t.startswith("Deepest cut is out of Z range") for t in titles())
    loaded.link.surface_z = None
    loaded._on_unlinked("test")
    assert any(t.startswith("Z reach unknown") for t in titles())


def test_dowel_holes_count_toward_the_deepest_cut(loaded):
    loaded.action_double_sided(True)
    loaded.action_registration("dowel")
    loaded.refresh_checks()
    reach = [c for c in loaded._checks if c.title.startswith("Z reach")]
    assert reach and "dowels" in reach[0].detail


# ------------------------------------------------------------------ rework
def _export_rework(win, region, tmp_path, monkeypatch, source_index=0):
    page = win.rework_page
    page.refresh_sources()
    page.source.setCurrentIndex(source_index)
    page.add_region(*region)
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "rework.nc"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    page._export()
    assert out.exists(), "nothing was written"
    return out


def test_rework_follows_the_height_map_when_one_is_active(loaded, tmp_path,
                                                          monkeypatch):
    """A rework exists because a spot came out shallow. Cutting it again
    without the surface the export used reproduces the miss."""
    x0, y0, x1, y1 = loaded.state.board.outline.bounds
    region = (x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    loaded.level_page._load_table({"rows": _tilted_map(), "apply": False,
                                   "show": False})
    flat = _export_rework(loaded, region, tmp_path / "flat", monkeypatch)
    assert len(_zs_below_zero(flat)) == 1            # one depth, everywhere
    loaded.level_page._load_table({"rows": _tilted_map(), "apply": True,
                                   "show": False})
    warped = _export_rework(loaded, region, tmp_path / "warped", monkeypatch)
    assert len(_zs_below_zero(warped)) > 3           # follows the slope
    assert "warped to the probed surface" in warped.read_text(encoding="utf-8")


def test_rework_on_a_double_sided_job_repeats_the_pass_that_was_cut(
        loaded, tmp_path, monkeypatch):
    """The state's own toolpaths are the plain board's. A double-sided job
    cuts the LAYOUT, which the dowel frame shifts across the bed; a rework
    clipped from the plain board was a file for a board cut somewhere else."""
    loaded.action_double_sided(True)
    page = loaded.rework_page
    page.refresh_sources()
    assert [page.source.itemData(i) for i in range(page.source.count())] \
        == ["traces", "top_traces", "cutout"]
    lay = loaded._ds_layout()
    lx0, ly0, lx1, ly1 = lay.outline.bounds
    bx0 = loaded.state.board.outline.bounds[0]
    assert abs(lx0 - bx0) > 1.0, "the layout does not shift this board"
    out = _export_rework(loaded, (lx0 - 2, ly0 - 2, lx1 + 2, ly1 + 2),
                         tmp_path, monkeypatch)
    # Motion lines only: the preamble homes with G28 X0 and dwells with G04.
    xs = [float(m.group(1))
          for line in out.read_text(encoding="utf-8").splitlines()
          if not line.startswith(("G28", "G04", "G4 ", "(", "%", "O"))
          for m in [re.search(r"X(-?\d+\.?\d*)", line)] if m]
    assert lx0 - 2.0 <= min(xs) and max(xs) <= lx1 + 2.0
    assert min(xs) > bx0 + 0.5 if lx0 > bx0 else max(xs) < bx0 - 0.5


def test_a_single_sided_job_offers_no_top_pass(loaded):
    page = loaded.rework_page
    page.refresh_sources()
    assert [page.source.itemData(i) for i in range(page.source.count())] \
        == ["traces", "cutout"]
