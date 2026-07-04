"""Manual bed-leveling: probe grid, height map, and toolpath warp."""
import math
from gerber2rml.toolpath import Move
from gerber2rml.engine.leveling import (
    probe_points, render_probe_point, write_probe_files,
    HeightMap, apply_leveling,
)


# ---- probe grid -----------------------------------------------------------

def test_probe_points_grid_inset_and_count():
    pts = probe_points((0, 0, 20, 10), nx=3, ny=2, margin=2.0)
    assert len(pts) == 6
    xs = sorted({x for x, _y in pts})
    ys = sorted({y for _x, y in pts})
    assert xs == [2.0, 10.0, 18.0]          # inset by margin, evenly spaced
    assert ys == [2.0, 8.0]


def test_probe_program_is_spindle_off_and_visits_point():
    g = render_probe_point(22.0, 8.0, idx=3, total=9, approach_z=2.0)
    lines = g.splitlines()
    assert "M5" in lines and "M3" not in lines   # spindle OFF for a hand touch-off
    assert "X22. Y8." in g
    assert g.strip().endswith("%")


def test_write_probe_files_one_per_point_plus_checklist(tmp_path):
    pts = probe_points((0, 0, 20, 10), nx=3, ny=2)
    written = write_probe_files(tmp_path, "lvl", pts)
    ncs = sorted(p.name for p in written if p.suffix == ".nc")
    assert ncs == [f"lvl_probe_{i:02d}.nc" for i in range(1, 7)]
    assert (tmp_path / "lvl_probe_checklist.txt").exists()


# ---- height map -----------------------------------------------------------

def test_plane_fit_recovers_known_tilt():
    # surface z = 0.01*x + 0.02*y + 0.1
    pts = [(x, y, 0.01 * x + 0.02 * y + 0.1)
           for x, y in [(0, 0), (10, 0), (0, 10), (10, 10)]]
    h = HeightMap.from_plane(pts)
    assert abs(h(5, 5) - (0.01 * 5 + 0.02 * 5 + 0.1)) < 1e-9


def test_bilinear_grid_interpolates_between_nodes():
    xs, ys = [0, 10], [0, 10]
    z = [[0.0, 0.2], [0.4, 1.0]]            # z[j][i] at (xs[i], ys[j])
    h = HeightMap.from_grid(xs, ys, z)
    assert abs(h(0, 0) - 0.0) < 1e-9
    assert abs(h(10, 10) - 1.0) < 1e-9
    assert abs(h(5, 0) - 0.1) < 1e-9        # midpoint of bottom edge
    assert abs(h(5, 5) - 0.4) < 1e-9        # centre = mean of 4 corners


def test_from_points_uses_grid_when_complete():
    pts = [(x, y, 0.1 * (x + y)) for y in (0, 10) for x in (0, 10)]
    h = HeightMap.from_points(pts, nx=2, ny=2)
    assert abs(h(5, 5) - 0.1 * 10) < 1e-9   # bilinear centre


# ---- toolpath warp --------------------------------------------------------

def test_warp_offsets_cut_z_by_surface():
    h = HeightMap.from_plane([(0, 0, 0.0), (10, 0, 0.1), (0, 10, 0.0)])  # tilt in x
    tp = [[Move(0, 0, -0.15), Move(10, 0, -0.15)]]
    out = apply_leveling(tp, h, max_seg=2.0)
    # the move to (10,0): surface is +0.1 there, so cut Z rides up to -0.05
    assert abs(out[0][-1].z - (-0.15 + 0.1)) < 1e-9
    assert abs(out[0][-1].x - 10.0) < 1e-9


def test_warp_subdivides_long_feed_moves():
    h = HeightMap.from_plane([(0, 0, 0.0), (10, 0, 0.1), (0, 10, 0.0)])
    tp = [[Move(0, 0, -0.15), Move(10, 0, -0.15)]]
    out = apply_leveling(tp, h, max_seg=1.0)
    # 10 mm move at 1 mm steps -> ~10 sub-moves (plus the start point)
    assert len(out[0]) >= 10
    # a midpoint sub-move sits at half the tilt correction
    mid = [m for m in out[0] if abs(m.x - 5.0) < 1e-6][0]
    assert abs(mid.z - (-0.15 + 0.05)) < 1e-9


def test_warp_leaves_rapids_unsubdivided_but_clearance_tracks():
    h = HeightMap.from_plane([(0, 0, 0.0), (10, 0, 0.1), (0, 10, 0.0)])
    tp = [[Move(0, 0, 2.0, rapid=True), Move(10, 0, 2.0, rapid=True)]]
    out = apply_leveling(tp, h, max_seg=1.0)
    assert len(out[0]) == 2                  # rapids not subdivided
    assert abs(out[0][1].z - (2.0 + 0.1)) < 1e-9


# ---- mesh sanity / probing advice -------------------------------------------

def _mega_mesh():
    """The real MegaPCB top mesh that produced the uncut middle band."""
    xs = [9.071, 103.550, 198.529]
    ys = [11.953, 72.416, 131.378]
    z = [[0.0, 0.25, 0.25], [0.02, 0.02, -0.03], [0.05, 0.22, 0.17]]
    return [(x, y, z[j][i]) for j, y in enumerate(ys) for i, x in enumerate(xs)]


def test_flag_outliers_finds_single_bad_point_not_smooth_bow():
    from gerber2rml.engine.leveling import flag_outliers
    # smooth quadratic bow: legitimate warp, nothing flagged
    bow = [(x, y, 0.0005 * (x - 50) ** 2 / 50)
           for y in (0, 50, 100) for x in (0, 50, 100)]
    assert flag_outliers(bow, tol=0.05) == []
    # same bow with one flaky touch 0.3 mm off -> exactly that point flagged
    bad = list(bow)
    bad[4] = (bad[4][0], bad[4][1], bad[4][2] + 0.30)
    flags = flag_outliers(bad, tol=0.10)
    assert flags and flags[0][0] == 4 and flags[0][1] > 0.15


def test_recommend_depth_on_the_mega_mesh_says_cut_deeper():
    from gerber2rml.engine.leveling import recommend_depth
    r = recommend_depth(_mega_mesh(), nx=3, ny=3)
    # 0.15 mm was NOT enough on this board; the advisor must say so
    assert r["depth"] >= 0.16
    assert abs(r["range"] - 0.28) < 1e-9
    assert r["worst_spread"] >= 0.2
    assert "cell" in r["detail"]


def test_recommend_depth_flat_mesh_keeps_default():
    from gerber2rml.engine.leveling import recommend_depth
    flat = [(x, y, 0.005) for y in (0, 50) for x in (0, 50, 100)]
    r = recommend_depth(flat, nx=3, ny=2)
    assert r["depth"] == 0.15


def test_suggest_refinement_rows_on_the_mega_mesh():
    from gerber2rml.engine.leveling import suggest_refinement_rows
    s = suggest_refinement_rows(_mega_mesh(), nx=3, ny=3, budget=0.08)
    # the surface jumps ~0.23 mm between BOTH row pairs -> two new rows
    assert len(s["rows"]) == 2
    assert abs(s["rows"][0] - (11.953 + 72.416) / 2) < 1e-3
    assert abs(s["rows"][1] - (72.416 + 131.378) / 2) < 1e-3
    # columns never jump more than 0.25-0.02 across a row? they do at the front
    # row (0 -> 0.25): the left column gap is flagged too
    assert s["cols"]


def test_suggest_refinement_quiet_on_gentle_mesh():
    from gerber2rml.engine.leveling import suggest_refinement_rows
    gentle = [(x, y, 0.0003 * x) for y in (0, 60, 120) for x in (0, 100, 200)]
    s = suggest_refinement_rows(gentle, nx=3, ny=3, budget=0.08)
    assert s == {"rows": [], "cols": []}
