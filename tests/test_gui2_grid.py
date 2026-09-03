"""The probe grid goes where the machine can get to, and a finished probe is
used.

Found on a real sheet, 2026-09-03: two boards placed 2 mm past the end of
the X travel put the grid's last column at X 203.22 on a 203.2 mm bed, and
every point in it failed with no clue why. The map then sat unapplied, so
the flex margin charged its whole range.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
BED_X, BED_Y = 203.2, 152.4


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.load_folder(str(FIXT))
    w.select_step("level")
    yield w
    w.close()


def _grid(win, nx=5, ny=5):
    said = []
    win.say = lambda l, t: said.append((l, t))
    win.level_page.nx.setValue(nx)
    win.level_page.ny.setValue(ny)
    win.level_page._build()
    return win.level_page._points, said[-1]


def test_the_grid_stays_inside_the_travel(loaded):
    loaded.action_stock(220.0, 160.0, 0.0, 0.0)       # copper past the bed
    x0, _y0, x1, _y1 = loaded.work_bounds()
    loaded.action_place(loaded.state.place_x + (BED_X + 3.0) - x1,
                        loaded.state.place_y)          # 3 mm off the right
    assert loaded.work_bounds()[2] > BED_X
    pts, (level, text) = _grid(loaded)
    assert pts and max(x for x, _y in pts) <= BED_X
    assert level == "warn" and "past the travel" in text


def test_the_grid_stays_on_the_copper(loaded):
    x0, y0, x1, y1 = loaded.work_bounds()
    loaded.action_stock(x1 - x0 - 30.0, y1 - y0, x0, y0)  # 30 mm short
    pts, (level, text) = _grid(loaded)
    assert pts and max(x for x, _y in pts) <= x1 - 30.0
    assert level == "warn" and "past the copper" in text


def test_a_job_on_the_copper_and_the_bed_gets_the_whole_grid(loaded):
    loaded.action_stock(BED_X, BED_Y, 0.0, 0.0)
    x0, y0, x1, y1 = loaded.work_bounds()
    pts, (level, _text) = _grid(loaded)
    assert level == "info"
    assert min(x for x, _y in pts) == pytest.approx(x0 + 2.0, abs=1e-3)
    assert max(x for x, _y in pts) == pytest.approx(x1 - 2.0, abs=1e-3)


def test_a_finished_probe_switches_the_warp_on(loaded):
    page = loaded.level_page
    rows = [[f"{x:.3f}", f"{y:.3f}", "0.1000"]
            for y in (10.0, 50.0, 90.0) for x in (10.0, 50.0, 90.0)]
    page._load_table({"rows": rows, "apply": False, "show": False})
    assert not page.use_chk.isChecked()
    said = []
    loaded.say = lambda l, t: said.append((l, t))
    page._on_done("", None)
    assert page.use_chk.isChecked()
    assert "warp the exported cut" in said[-1][1]
    assert loaded.level_page.height_map(side="bottom") is not None
