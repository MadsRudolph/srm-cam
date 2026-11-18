"""How a board is made: read from KiCad, guessed from its gaps, chosen here,
and what it changes - the checks, the plan and the export."""
import json
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, box

from gerber2rml.engine import method as fab

FIX = Path(__file__).parent / "fixtures"


def test_the_gap_decides_the_guess():
    assert fab.guess_from_gap(None) == fab.FLAT
    assert fab.guess_from_gap(0.9) == fab.FLAT
    assert fab.guess_from_gap(0.8) == fab.FLAT
    assert fab.guess_from_gap(0.5) == fab.BALL
    assert fab.guess_from_gap(0.44) == fab.BALL
    assert fab.guess_from_gap(0.25) == fab.LASER


def test_narrowest_gap_is_between_nets_only():
    copper = MultiPolygon([box(0, 0, 1, 1), box(1.3, 0, 2, 1)])
    assert fab.narrowest_gap(copper) == pytest.approx(0.3)
    # Two pieces of one net are no gap at all.
    assert fab.narrowest_gap(copper, nets=[{"GND"}, {"GND"}]) is None


def test_a_profile_says_flat_or_ball():
    assert fab.from_profile(0.8) == fab.FLAT
    assert fab.from_profile(0.44) == fab.BALL
    assert fab.from_profile(None) == fab.FLAT


def _write(folder, boards):
    (folder / "method.json").write_text(json.dumps({"boards": boards}))


def test_kicad_method_file_is_read(tmp_path):
    assert fab.read_kicad(tmp_path) is None
    _write(tmp_path, {"output.kicad_pcb": {"method": "laser"}})
    assert fab.read_kicad(tmp_path, "output") == fab.LASER
    assert fab.read_kicad(tmp_path) == fab.LASER


def test_kicad_method_file_with_two_boards_matches_the_stem(tmp_path):
    _write(tmp_path, {"a.kicad_pcb": {"method": "mill_ball"},
                      "b.kicad_pcb": {"method": "laser"}})
    assert fab.read_kicad(tmp_path, "a") == fab.BALL
    assert fab.read_kicad(tmp_path, "b") == fab.LASER
    assert fab.read_kicad(tmp_path, "c") is None
    assert fab.read_kicad(tmp_path) is None


def test_a_bad_method_file_is_ignored(tmp_path):
    (tmp_path / "method.json").write_text("not json")
    assert fab.read_kicad(tmp_path) is None
    _write(tmp_path, {"x.kicad_pcb": {"method": "plasma"}})
    assert fab.read_kicad(tmp_path) is None


def test_the_laser_fixture_is_guessed_laser():
    from gerber2rml.loader import load_board
    board = load_board(FIX / "curtain_drive")
    mid, gap = fab.guess(board)
    assert mid == fab.LASER and gap < 0.44


# -------------------------------------------------------------- the plan
@pytest.fixture
def state():
    from gerber2rml.app.state import ProjectState
    st = ProjectState()
    st.load(FIX / "mosfet_test")
    return st


def test_a_laser_plan_drills_and_cuts_out_then_lasers(state):
    from gerber2rml.gui2 import runplan
    plan = runplan.build(state, method="laser",
                         laser_jobs=("traces", "mask", "silk"))
    ops = [s.op for s in plan.run_steps]
    assert "traces" not in ops and "top_traces" not in ops
    assert ops[-1] == "cutout" and "drill" in ops
    laser = [s.key for s in plan if s.machine == "laser"]
    assert laser == ["laser_traces", "laser_mask", "laser_silk"]
    keys = [s.key for s in plan]
    # The mill comes first: the laser lines up on the drilled holes.
    assert keys.index("cutout_run") < keys.index("laser_traces")
    assert plan.by_key("autorun").title == "Drill and cut out"


def test_a_mill_plan_keeps_its_traces_and_has_no_laser_copper(state):
    from gerber2rml.gui2 import runplan
    plan = runplan.build(state, laser_jobs=("traces", "mask"))
    assert any(s.op == "traces" for s in plan.run_steps)
    assert plan.by_key("laser_traces") is None
    assert plan.by_key("laser_mask") is not None


def test_no_plan_has_a_dry_run(state):
    from gerber2rml.gui2 import runplan
    for double in (False, True):
        plan = runplan.build(state, double_sided=double,
                             registration="fiducial")
        assert not any(s.op == "airpass" for s in plan)


def test_the_export_writes_no_dry_run(state, tmp_path):
    written = state.export(tmp_path)
    assert not any("airpass" in Path(p).name for p in written)


def test_a_laser_export_has_no_traces(state, tmp_path):
    written = [Path(p).name for p in state.export(tmp_path, traces=False)]
    assert not any("traces" in n for n in written)
    assert any("cutout" in n for n in written)
    assert any("drill" in n for n in written)


# -------------------------------------------------------------- panels
def test_arranged_boards_wrap_to_the_sheet():
    from gerber2rml.app import panel

    class M:
        def __init__(self, w, h):
            self.w, self.h, self.place_x, self.place_y = w, h, 0.0, 0.0

        def bounds(self):
            return (self.place_x, self.place_y, self.place_x + self.w,
                    self.place_y + self.h)

    ms = [M(60, 40), M(60, 40), M(60, 30)]
    panel.arrange_rows(ms, gap=4, width=130)
    assert [m.bounds()[:2] for m in ms] == [(0, 0), (64, 0), (0, 44)]
    panel.arrange_rows(ms, gap=4, width=None)          # one row, as before
    assert ms[2].bounds()[0] == pytest.approx(128)
