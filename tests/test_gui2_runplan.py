"""One order, stated once — enforced rather than asserted in a comment.

The first interface described the machining order in three places that could
disagree, and untangling them took a commit of its own. The second interface
has one list of steps, and the whole point of these tests is that the list is
checked against the files the ENGINE writes rather than against a copy of the
order kept in a test.

So each of these exports the real demo board with the real engine and compares
the plan's file names, in sequence, against what actually landed on disk. A
step added to ``cli.build_jobs`` and not to ``gui2/runplan.py`` fails here; so
does a step reordered in either place.
"""
from pathlib import Path

import pytest

from gerber2rml.app.state import ProjectState
from gerber2rml.gui2 import runplan

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def state():
    st = ProjectState()
    st.name = "demo"
    st.load(FIXT)
    return st


def _toolpath_files(written, ext=".nc"):
    return [Path(p).name for p in written if Path(p).suffix == ext]


def test_single_sided_plan_matches_what_the_engine_writes(state, tmp_path):
    written = state.export(tmp_path)
    plan = runplan.build(state)
    assert plan.files == _toolpath_files(written)


def test_single_sided_plan_starts_with_the_dry_run(state):
    """Step 0 is the airpass, and it is first because it is meant to be run
    first — it is the cheapest board-saving check in the product."""
    plan = runplan.build(state)
    first = plan.run_steps[0]
    assert first.ordinal == 0
    assert first.op == "airpass"
    assert "airpass" in first.file
    assert first.bit is None            # spindle off: no bit is engaged


def test_the_cut_out_is_last_and_says_why(state):
    plan = runplan.build(state)
    last = plan.run_steps[-1]
    assert last.op == "cutout"
    assert "last" in last.caution.lower()
    assert "free" in last.note.lower() or "free" in last.caution.lower()


def test_double_sided_plan_matches_what_the_engine_writes(state, tmp_path):
    from gerber2rml.doublesided import build_double_sided, layout_double_sided
    lay = layout_double_sided(FIXT)
    written = build_double_sided(FIXT, tmp_path, state.name, trace=state.trace,
                                 drill=state.drill, cutout=state.cutout)
    plan = runplan.build(state, double_sided=True, holes=lay.holes,
                         align_holes=lay.align_holes)
    assert plan.files == _toolpath_files(written)


def test_double_sided_puts_the_cut_out_after_the_flip(state):
    """Cutting the outline before the flip frees the board from the dowels it
    is registered on — which is how a nearly finished double-sided board
    becomes scrap."""
    plan = runplan.build(state, double_sided=True)
    keys = [s.key for s in plan]
    assert keys.index("flip") < keys.index("top_traces") < keys.index("cutout_run")


def test_the_dowel_step_is_marked_irreversible(state):
    """It drills into the sacrificial bed, so re-zeroing and trying again does
    not undo it."""
    plan = runplan.build(state, double_sided=True)
    align = plan.by_key("align")
    assert align.irreversible
    assert align.caution


def test_fiducial_registration_is_not_irreversible(state):
    """Fiducial holes go through the stock only, never into the bed, so this
    one genuinely can be re-run."""
    plan = runplan.build(state, double_sided=True, registration="fiducial")
    assert not plan.by_key("align").irreversible


def test_multi_bit_drilling_names_one_step_per_file(state, tmp_path):
    state.drill.single_bit = False
    written = state.export(tmp_path)
    plan = runplan.build(state)
    assert plan.files == _toolpath_files(written)
    assert len([s for s in plan.run_steps if s.op == "drill"]) >= 2


def _walk_the_spindle(plan):
    """Follow the plan the way an operator would, tracking what is in the collet.

    Hands-on steps put a tool in; run steps need one. This models the thing the
    plan is actually for, so it catches both a missing bit-change step and a
    superfluous one.
    """
    spindle = None
    for s in plan:
        if s.kind == "handoff" and s.tool is not None:
            assert s.tool != spindle, (
                f"{s.key} tells you to fit the tool that is already in the "
                f"spindle")
            spindle = s.tool
        elif s.kind == "run" and s.tool is not None:
            assert s.tool == spindle, (
                f"{s.key} needs {runplan.tool_label(s.tool)} but the spindle "
                f"holds {runplan.tool_label(spindle)}")
    return spindle


def test_one_bit_for_the_whole_job_means_no_bit_change_steps(state):
    """The normal case in this lab: one 0.8 mm endmill isolates, drills and
    cuts out, and never leaves the collet.

    A plan that told you to change bits three times would be three rows of
    instruction you never follow — which is how a plan stops being read.
    """
    for job in (state.trace, state.drill, state.cutout):
        job.bit_diameter = 0.8
    plan = runplan.build(state)
    assert plan.single_tool
    assert plan.tool_label == "0.80 mm flat endmill"
    assert runplan.tool_changes(plan) == []
    _walk_the_spindle(plan)


def test_one_bit_holds_on_a_double_sided_job_too(state):
    for job in (state.trace, state.drill, state.cutout):
        job.bit_diameter = 0.8
    plan = runplan.build(state, double_sided=True)
    assert plan.single_tool
    assert runplan.tool_changes(plan) == []
    # ...but the flip is still a hands-on step, because the other face of the
    # board is not at the same height.
    flip = plan.by_key("flip")
    assert flip is not None and "re-zero z" in flip.detail.lower()
    _walk_the_spindle(plan)


def test_a_bit_change_step_appears_exactly_where_the_tool_changes(state):
    """A V-bit trace pass with a flat-endmill drill and cut-out: one change,
    after the traces and before the drilling."""
    state.trace.tool_type = "vbit"
    plan = runplan.build(state)
    assert not plan.single_tool
    changes = runplan.tool_changes(plan)
    assert len(changes) == 1, changes
    keys = [s.key for s in plan]
    assert keys.index("traces_run") < keys.index(changes[0][0]) \
        < keys.index("drill_run")
    _walk_the_spindle(plan)


def test_per_diameter_drilling_gets_a_change_per_diameter(state):
    """Opting out of single-bit drilling really does mean a bit change per hole
    size, and the cut-out needs its own bit back afterwards."""
    state.drill.single_bit = False
    plan = runplan.build(state)
    diameters = {round(d, 2) for _x, _y, d in state.board.holes}
    assert len(runplan.tool_changes(plan)) >= len(diameters) - 1
    _walk_the_spindle(plan)


def test_a_v_bit_is_never_confused_with_a_flat_of_the_same_number(state):
    """Two tools are the same tool only if they are the same tool. A 30° V-bit
    and a flat endmill are different even when the diameters line up."""
    state.trace.tool_type = "vbit"
    assert runplan.tool_id(state.trace, trace=True) \
        != runplan.tool_id(state.drill)


def test_the_origin_step_comes_before_the_dry_run(state):
    """The dry run holds the bit 5 mm above the WORK Z ZERO, so it means
    nothing until that zero exists — and VPanel will not output a file without
    an origin either."""
    plan = runplan.build(state)
    keys = [s.key for s in plan]
    assert keys.index("origin") < keys.index("airpass")
    origin = plan.by_key("origin")
    assert origin.tool is not None, "it has to say which bit goes in"
    assert "origin" in origin.title.lower()


def test_every_hands_on_step_says_never_xy(state):
    """The standing rule of the whole product. If a hands-on step stops saying
    it, someone re-zeroes XY and the passes stop registering with each other."""
    plan = runplan.build(state, double_sided=True)
    hands_on = [s for s in plan if s.kind == "handoff"]
    assert hands_on
    for s in hands_on:
        text = (s.title + " " + s.detail + " " + s.note).lower()
        assert "xy" in text, s.key
        assert "never re-zero xy" in text or "only z is ever re-zeroed" in text \
            or "leave xy alone" in text, s.key


def test_estimates_flow_from_the_files_to_the_total(state, tmp_path):
    written = state.export(tmp_path)
    plan = runplan.build(state)
    from gerber2rml.engine.estimate import estimate_file_seconds
    plan.apply_estimates({Path(p).name: estimate_file_seconds(p)
                          for p in written if Path(p).suffix == ".nc"})
    assert plan.total_seconds > 0
    assert all(s.seconds is not None for s in plan.run_steps)


def test_the_plan_survives_a_board_that_is_not_loaded_yet():
    """The rail is built before anything is open, so this must not raise."""
    plan = runplan.build(ProjectState())
    assert plan.by_key("setup") is not None
    assert plan.run_steps
