"""The dry-run outline: prove the stock is under the toolpath before cutting.

Without the Arduino there is no probe and no live readout, so the only way a
student finds out the copper is misplaced is by cutting into the bed. This
traces where the board will be, with the spindle off and the bit held clear,
so a misplacement costs twenty seconds instead of a board.
"""
from shapely.geometry import Polygon, box

from gerber2rml.engine import airpass


def test_traces_the_board_outline_at_a_constant_safe_height():
    """It must never descend. The whole point is that nothing can be cut."""
    paths = airpass.air_path(box(0, 0, 20, 10), height=5.0)

    zs = {m.z for tp in paths for m in tp}
    assert zs == {5.0}


def test_the_loop_closes_so_the_bit_ends_where_it_started():
    paths = airpass.air_path(box(0, 0, 20, 10), height=5.0)
    moves = paths[0]

    first, last = moves[0], moves[-1]
    assert (round(first.x, 6), round(first.y, 6)) == (round(last.x, 6), round(last.y, 6))


def test_it_reaches_every_corner_of_the_board():
    """A student is watching the bit to see whether it stays over copper, so
    it has to actually visit the extremes."""
    paths = airpass.air_path(box(2, 3, 22, 13), height=5.0)
    pts = {(round(m.x, 3), round(m.y, 3)) for tp in paths for m in tp}

    for corner in ((2, 3), (22, 3), (22, 13), (2, 13)):
        assert corner in pts, f"{corner} missing from {sorted(pts)}"


def test_it_follows_a_non_rectangular_outline():
    """Boards are not always rectangles, and the interesting ones are not."""
    ell = Polygon([(0, 0), (30, 0), (30, 10), (10, 10), (10, 20), (0, 20)])

    pts = {(round(m.x, 3), round(m.y, 3))
           for tp in airpass.air_path(ell, height=4.0) for m in tp}

    assert (30.0, 10.0) in pts and (10.0, 20.0) in pts


def test_the_travel_is_a_feed_move_not_a_rapid():
    """A rapid is far too fast to react to. This is meant to be watched."""
    paths = airpass.air_path(box(0, 0, 20, 10), height=5.0)

    assert all(not m.rapid for m in paths[0][1:]), "only the approach may be rapid"


def test_the_rendered_program_never_starts_the_spindle():
    """The bit is going to pass over the stock at 5 mm with someone leaning in
    to look at it. It must not be spinning."""
    from gerber2rml.backends import gcode

    text = gcode.render(airpass.air_path(box(0, 0, 20, 10), height=5.0),
                        xy_feed=10.0, plunge_feed=1.0, spindle=False)

    words = text.split()
    assert "M3" not in words          # NB: not `"M3" not in text` - M30 ends the program
    assert not any(w.startswith("G04") for w in words)   # no spin-up dwell to wait on
    assert "M5" in words              # still commanded off, belt and braces


def test_the_normal_program_still_starts_the_spindle():
    """The default must not change — every cutting job depends on it."""
    from gerber2rml.backends import gcode

    text = gcode.render(airpass.air_path(box(0, 0, 20, 10), height=5.0),
                        xy_feed=10.0, plunge_feed=1.0)

    assert "M3" in text.split()


def test_rml_dry_run_leaves_the_spindle_off():
    """The RML path has to honour it too, or the fallback machine setting
    silently gives you a spinning bit."""
    from gerber2rml.backends import srm20

    text = srm20.render(airpass.air_path(box(0, 0, 20, 10), height=5.0),
                        xy_feed=10.0, plunge_feed=1.0, spindle=False)

    assert "!MC1" not in text
    assert "!MC0" in text


# --- it lands in the export, without anyone having to ask for it -----------

def test_export_includes_a_dry_run_file(tmp_path):
    from pathlib import Path
    from gerber2rml.cli import build_jobs

    fixt = Path(__file__).parent / "fixtures" / "mosfet_test"
    written = build_jobs(fixt, tmp_path, "board", machine="Roland SRM-20 (G-code)")

    names = [p.name for p in written]
    assert "board_airpass.nc" in names


def test_the_run_plan_tells_you_to_run_the_dry_run_first(tmp_path):
    """It is only worth anything if it happens before the first cut."""
    from pathlib import Path
    from gerber2rml.cli import build_jobs

    fixt = Path(__file__).parent / "fixtures" / "mosfet_test"
    build_jobs(fixt, tmp_path, "board", machine="Roland SRM-20 (G-code)")

    plan = (tmp_path / "board_runplan.txt").read_text(encoding="utf-8")
    assert "airpass" in plan
    assert plan.index("airpass") < plan.index("1. traces")


def _motion_xs(path):
    """X values of real motion lines. Excludes the G28 park, which is a machine
    -home move at X0 and would otherwise dominate any min()."""
    import re
    xs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("G28") or not line.startswith(("G0 ", "G1 ")):
            continue
        m = re.search(r"X(-?[\d.]+)", line)
        if m:
            xs.append(float(m.group(1)))
    return xs


def test_the_dry_run_is_placed_with_the_rest_of_the_job(tmp_path):
    """If it does not move with the board offset it traces the wrong place,
    which is worse than not having it at all."""
    from pathlib import Path
    from gerber2rml.cli import build_jobs

    fixt = Path(__file__).parent / "fixtures" / "mosfet_test"
    build_jobs(fixt, tmp_path / "a", "b", machine="Roland SRM-20 (G-code)")
    build_jobs(fixt, tmp_path / "b", "b", machine="Roland SRM-20 (G-code)",
               offset=(25.0, 40.0))

    ax = min(_motion_xs(tmp_path / "a" / "b_airpass.nc"))
    bx = min(_motion_xs(tmp_path / "b" / "b_airpass.nc"))

    assert round(bx - ax, 3) == 25.0
