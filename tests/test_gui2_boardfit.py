"""The drill-only page: pick pads, type where they really are, see the board
move to them, and write a drill file that lands there."""
import math
from pathlib import Path

import pytest

from gerber2rml.engine.fiducial import Transform
from gerber2rml.engine.gcode_parse import parse_nc
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    yield w
    w.close()


def _measure(page, t):
    """Fill every row with where ``t`` puts that pad."""
    holes = page.ctl.state.board.holes
    for r, i in enumerate(page.pads()):
        page._set_measured(r, *t.apply(*holes[i][:2]))


def test_step_is_on_the_single_sided_plan_only(win):
    assert win.plan.by_key("fitdrill") is not None
    win.action_double_sided(True)
    assert win.plan.by_key("fitdrill") is None


def test_measured_pads_fit_and_the_file_lands_on_them(win, tmp_path):
    win.select_step("fitdrill")
    page = win.boardfit_page
    assert win.inspector.stack.currentWidget() is page
    page.suggest()
    assert len(page.pads()) == 3
    assert page.current_fit() is None and not page.write_btn.isEnabled()

    t = Transform(math.radians(-1.5), 1.0, 12.0, -4.0)
    _measure(page, t)
    fit = win._board_fit
    assert fit is not None and page.write_btn.isEnabled()
    # The table holds microns, so the fit is as good as that.
    assert abs(fit.theta - t.theta) < 1e-4 and abs(fit.tx - t.tx) < 5e-3

    written = page.write_to(tmp_path)
    assert [p.name for p in written] == [f"{win.state.name}_drill_fitted.nc"]
    cuts = [(m.x, m.y) for path in parse_nc(written[0].read_text())
            for m in path if m.z < 0]
    bit = win.cutting_drill().bit_diameter
    for x, y, d in win.state.board.holes:
        mx, my = t.apply(x, y)
        reach = max(0.0, (d - bit) / 2) + 5e-3
        assert any(math.dist(c, (mx, my)) <= reach for c in cuts)


def test_a_mirrored_board_is_called_out(win):
    win.select_step("fitdrill")
    page = win.boardfit_page
    page.suggest()
    holes = win.state.board.holes
    for r, i in enumerate(page.pads()):
        x, y = holes[i][:2]
        page._set_measured(r, 200.0 - x, y)        # etched the other way round
    assert page._worst > 1.0
    assert "Too far out" in page.verdict.text()


def test_clicking_the_stage_adds_the_nearest_pad(win):
    win.select_step("fitdrill")
    page = win.boardfit_page
    x, y, _d = win.state.board.holes[2]
    page.pick_chk.setChecked(True)
    assert win.stage.mode == "pad"
    win.stage.pad_picked.emit(x + 0.2, y - 0.1)
    assert page.pads() == [2]
    win.stage.pad_picked.emit(x, y)                 # the same one again
    assert page.pads() == [2]


def test_loading_another_board_forgets_the_pads(win):
    win.select_step("fitdrill")
    win.boardfit_page.suggest()
    _measure(win.boardfit_page, Transform(0.0, 1.0, 1.0, 1.0))
    assert win._board_fit is not None
    win.load_folder(str(FIXT))
    assert win.boardfit_page.pads() == [] and win._board_fit is None
