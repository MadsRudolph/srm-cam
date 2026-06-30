from pathlib import Path
from gerber2rml.doublesided import (
    layout_double_sided, preview_layout_double_sided, reflect_x, reflect_holes,
    DowelSpec, PIN_LARGE, PIN_SMALL, CLEAR_LARGE, CLEAR_SMALL,
)

# align_holes carry the milled-HOLE diameter = pin + default per-pin clearance
# (the SRM-20 kerf differs by diameter; see CLEAR_LARGE / CLEAR_SMALL).
HOLE_LARGE = PIN_LARGE + CLEAR_LARGE
HOLE_SMALL = PIN_SMALL + CLEAR_SMALL

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_reflect_x_fixes_axis():
    assert reflect_x([(10.0, 5.0, 0.8)], x_axis=10.0)[0][0] == 10.0
    assert reflect_x([(12.0, 5.0, 0.8)], x_axis=10.0)[0][0] == 8.0


# ---- fresh-milled dowels -------------------------------------------------

def test_fresh_pins_on_axis_above_and_below_keyed_by_diameter():
    lay = layout_double_sided(FIXT)            # default = fresh
    assert len(lay.align_holes) == 2
    (bx, by, bd), (tx, ty, td) = lay.align_holes
    # both on the vertical flip axis
    assert lay.axis == "vertical"
    assert abs(bx - lay.flip_pos) < 1e-6 and abs(tx - lay.flip_pos) < 1e-6
    _x0, y0, _x1, y1 = lay.outline.bounds
    assert by < y0 and ty > y1                 # one below the board, one above
    # keyed: large below, small above, and the two differ
    assert abs(bd - HOLE_LARGE) < 1e-6 and abs(td - HOLE_SMALL) < 1e-6
    assert abs(bd - td) > 0.5
    # the pins hug the edges (offset ~ edge_offset), NOT 50 mm out in bare bed
    assert (y0 - by) < 12.0 and (ty - y1) < 12.0


def test_top_outline_reflected_about_vertical_axis():
    lay = layout_double_sided(FIXT)
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    tx0, ty0, tx1, ty1 = lay.top_outline.bounds
    assert abs(oy0 - ty0) < 1e-6 and abs(oy1 - ty1) < 1e-6      # Y preserved
    assert abs(((ox0 + ox1) / 2) - lay.flip_pos) < 1e-6        # board centred on axis
    assert abs(((tx0 + tx1) / 2) - lay.flip_pos) < 1e-6        # reflected copy too


def test_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT)
    (hx, hy, hd) = lay.holes[0]
    assert any(abs(rx - (2 * lay.flip_pos - hx)) < 1e-6 and abs(ry - hy) < 1e-6
               for (rx, ry, rd) in reflect_x(lay.holes, lay.flip_pos))


# ---- left/right placement (top-bottom flip) ------------------------------

def test_leftright_pins_on_horizontal_axis_beside_the_board():
    lay = layout_double_sided(FIXT, dowels=DowelSpec(placement="leftright"))
    assert lay.axis == "horizontal"
    (lx, ly, ld), (rx, ry, rd) = lay.align_holes
    # both dowels share the horizontal flip axis (constant y)
    assert abs(ly - lay.flip_pos) < 1e-6 and abs(ry - lay.flip_pos) < 1e-6
    x0, _y0, x1, _y1 = lay.outline.bounds
    assert lx < x0 and rx > x1                  # one left of the board, one right
    # keyed: large left, small right, and the two differ
    assert abs(ld - HOLE_LARGE) < 1e-6 and abs(rd - HOLE_SMALL) < 1e-6
    assert abs(ld - rd) > 0.5


def test_leftright_top_outline_reflected_about_horizontal_axis():
    lay = layout_double_sided(FIXT, dowels=DowelSpec(placement="leftright"))
    ox0, _oy0, ox1, _oy1 = lay.outline.bounds
    tx0, ty0, tx1, ty1 = lay.top_outline.bounds
    assert abs(ox0 - tx0) < 1e-6 and abs(ox1 - tx1) < 1e-6      # X preserved
    # board (and its reflected copy) centred on the horizontal flip axis
    _ox0b, oy0, _ox1b, oy1 = lay.outline.bounds
    assert abs(((oy0 + oy1) / 2) - lay.flip_pos) < 1e-6
    assert abs(((ty0 + ty1) / 2) - lay.flip_pos) < 1e-6


def test_leftright_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT, dowels=DowelSpec(placement="leftright"))
    (hx, hy, hd) = lay.holes[0]
    # reflecting a hole about the horizontal flip axis lands on its mirror
    assert any(abs(rx - hx) < 1e-6 and abs(ry - (2 * lay.flip_pos - hy)) < 1e-6
               for (rx, ry, rd) in reflect_holes(lay.holes, "horizontal", lay.flip_pos))


def test_leftright_build_runplan_says_top_to_bottom(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    build_double_sided(FIXT, tmp_path, name="lr", machine="Roland SRM-20",
                       dowels=DowelSpec(placement="leftright"))
    plan = (tmp_path / "lr_runplan.txt").read_text()
    assert "TOP-TO-BOTTOM" in plan and "LEFT" in plan and "RIGHT" in plan
    assert "LEFT-TO-RIGHT" not in plan


# ---- grid-seated dowels --------------------------------------------------

def test_grid_pins_land_on_grid_holes_and_are_keyed_by_spacing():
    spec = DowelSpec(mode="grid", pitch_x=14.2, pitch_y=14.2, grid_pin=4.0)
    lay = layout_double_sided(FIXT, dowels=spec)
    (bx, by, bd), (tx, ty, td) = lay.align_holes
    # both on the same grid column (= the flip axis), and that column is a
    # multiple of the pitch from the datum hole at the origin
    assert abs(bx - lay.flip_pos) < 1e-6 and abs(tx - lay.flip_pos) < 1e-6
    assert abs(round(lay.flip_pos / 14.2) - lay.flip_pos / 14.2) < 1e-6
    # each dowel sits on a grid row (multiple of the pitch)
    for y in (by, ty):
        assert abs(round(y / 14.2) - y / 14.2) < 1e-6
    # uniform diameter = the grid hole size
    assert abs(bd - 4.0) < 1e-6 and abs(td - 4.0) < 1e-6
    # keyed by ASYMMETRIC spacing: the two edge gaps differ
    _x0, y0, _x1, y1 = lay.outline.bounds
    assert abs((y0 - by) - (ty - y1)) > 0.5


def test_grid_and_fresh_keep_positive_quadrant():
    for spec in (DowelSpec(), DowelSpec(mode="grid")):
        lay = layout_double_sided(FIXT, dowels=spec)
        for (x, y, _d) in lay.align_holes:
            assert x > 0 and y > 0
        assert lay.outline.bounds[0] > 0 and lay.outline.bounds[1] > 0


# ---- job building --------------------------------------------------------

def test_build_double_sided_writes_jobs(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob
    written = build_double_sided(FIXT, tmp_path, name="ds", machine="Roland SRM-20",
                                 trace=TraceJob(), drill=DrillJob(), cutout=CutoutJob())
    names = {p.name for p in written}
    for n in ("ds_align.rml", "ds_bottom_traces.rml", "ds_top_traces.rml",
              "ds_cutout.rml"):
        assert n in names
    assert "ds_bottom_drill.rml" in names      # single-bit default: one combined file
    for p in written:
        if p.suffix == ".rml":
            t = p.read_text()
            assert t.startswith("^IN;!MC1;") and t.rstrip().endswith("!MC0;^IN;")


def test_double_sided_leveling_warps_bottom_only(tmp_path):
    import re
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob

    # an X-tilt height map (deeper as x grows), in the bottom-side machine frame.
    # lead_in off: this test is about leveling, and the ramp would add its own Z
    # variation that masks the leveled-vs-flat distinction (lead-in has its own tests).
    level = lambda x, y: -0.003 * x
    written = build_double_sided(
        FIXT, tmp_path, name="lv", machine="Roland SRM-20 (G-code)",
        trace=TraceJob(), drill=DrillJob(), cutout=CutoutJob(), level=level,
        lead_in=False)

    def cut_zs(name):
        t = (tmp_path / name).read_text()
        zs = [float(m) for m in re.findall(r"Z(-?[0-9.]+)", t)]
        return {round(z, 3) for z in zs if z < 0.4}        # drop travel/lift heights

    assert len(cut_zs("lv_bottom_traces.nc")) > 5          # leveled -> many Z values
    assert len(cut_zs("lv_top_traces.nc")) <= 2            # NOT leveled -> flat depth
    assert "BOTTOM-side" in (tmp_path / "lv_runplan.txt").read_text()


def test_build_top_traces_leveled_re_export(tmp_path):
    import re
    from gerber2rml.doublesided import build_top_traces
    from gerber2rml.config import TraceJob

    def cut_zs(p):
        zs = [float(m) for m in re.findall(r"Z(-?[0-9.]+)", p.read_text())]
        return {round(z, 3) for z in zs if z < 0.4}

    # lead_in off: this test isolates leveling; the ramp's Z steps are tested
    # separately in test_leadin.py.
    flat = build_top_traces(FIXT, tmp_path / "a", "tt", trace=TraceJob(),
                            machine="Roland SRM-20 (G-code)", level=None, lead_in=False)
    lvl = build_top_traces(FIXT, tmp_path / "b", "tt", trace=TraceJob(),
                           machine="Roland SRM-20 (G-code)", level=lambda x, y: -0.003 * x,
                           lead_in=False)
    assert flat.name == "tt_top_traces.nc"           # overwrites the full-export file
    assert len(cut_zs(flat)) <= 2                     # unleveled -> flat depth
    assert len(cut_zs(lvl)) > 5                       # leveled -> warped Z


def test_grid_mode_build_and_runplan(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    written = build_double_sided(FIXT, tmp_path, name="g", machine="Roland SRM-20",
                                 dowels=DowelSpec(mode="grid"))
    names = {p.name for p in written}
    for n in ("g_align.rml", "g_bottom_traces.rml", "g_top_traces.rml", "g_cutout.rml"):
        assert n in names
    plan = (tmp_path / "g_runplan.txt").read_text()
    assert "grid" in plan.lower() and "datum grid hole" in plan


def test_layout_offset_shifts_board_and_dowels():
    a = layout_double_sided(FIXT)
    b = layout_double_sided(FIXT, offset=(10.0, 20.0))
    ax0, ay0, _ax1, _ay1 = a.outline.bounds
    bx0, by0, _bx1, _by1 = b.outline.bounds
    assert abs((bx0 - ax0) - 10.0) < 1e-6 and abs((by0 - ay0) - 20.0) < 1e-6
    # the dowels move with the job so registration is preserved
    assert abs(b.align_holes[0][0] - (a.align_holes[0][0] + 10.0)) < 1e-6
    assert abs(b.align_holes[0][1] - (a.align_holes[0][1] + 20.0)) < 1e-6


def _deepest_z(path):
    zs = [int(line.split(",")[2].rstrip(";")) for line in path.read_text().splitlines()
          if line.startswith("Z")]
    return min(zs)


def test_align_drills_deeper_than_board_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import DrillJob
    written = build_double_sided(FIXT, tmp_path, name="d", machine="Roland SRM-20",
                                 drill=DrillJob(), align_depth=6.0)
    bottom_drills = [p for p in written if p.name.startswith("d_bottom_drill")]
    deepest_board = min(_deepest_z(p) for p in bottom_drills)
    assert _deepest_z(tmp_path / "d_align.rml") < deepest_board


def test_bottom_drill_excludes_alignment_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    lay = layout_double_sided(FIXT)
    written = build_double_sided(FIXT, tmp_path, name="d")
    ax, ay, _d = lay.align_holes[0]
    token = f"Z{round(ax * 100)},{round(ay * 100)},"   # 100 RML units/mm (SRM-20)
    for p in written:
        if p.name.startswith("d_bottom_drill_"):
            assert token not in p.read_text()    # pinned hole is never re-drilled


def test_preview_layout_registers_layers_on_holes():
    from shapely.geometry import Point
    lay = preview_layout_double_sided(FIXT)

    def on(geom, x, y):
        return geom.distance(Point(x, y)) < 0.5

    assert any(on(lay.bottom_copper, x, y) and on(lay.top_copper, x, y)
               for (x, y, _d) in lay.holes)
    # pins still on a vertical axis, above & below the board
    assert abs(lay.align_holes[0][0] - lay.flip_pos) < 1e-6
    _bx0, by0, _bx1, by1 = lay.outline.bounds
    assert lay.align_holes[0][1] < by0 and lay.align_holes[1][1] > by1


def test_single_bit_double_sided_one_bottom_drill_file(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import DrillJob
    written = build_double_sided(FIXT, tmp_path, name="d", machine="Roland SRM-20",
                                 drill=DrillJob(single_bit=True, bit_diameter=0.8))
    drills = sorted(p.name for p in written if "_bottom_drill" in p.name)
    assert drills == ["d_bottom_drill.rml"]


def test_align_only_writes_just_the_dowel_file(tmp_path):
    """build_align_only emits ONLY the dowel-hole job, byte-identical to the
    _align file a full build would produce (so a re-cut lands on the holes)."""
    from gerber2rml.doublesided import build_align_only, build_double_sided
    spec = DowelSpec(clearance_large=0.2, clearance_small=0.2)
    only = build_align_only(FIXT, tmp_path / "only", "b", dowels=spec,
                            machine="Roland SRM-20 (G-code)")
    assert [p.name for p in (tmp_path / "only").iterdir()] == ["b_align.nc"]
    full = build_double_sided(FIXT, tmp_path / "full", "b", dowels=spec,
                              machine="Roland SRM-20 (G-code)")
    align_full = next(p for p in full if p.name == "b_align.nc")
    assert only.read_text() == align_full.read_text()


def test_pin_clearance_widens_holes_without_moving_centres():
    """Bumping a clearance grows the milled hole but leaves the dowel centre
    (and the whole placement) put, so a re-cut registers on the existing hole."""
    base = layout_double_sided(
        FIXT, dowels=DowelSpec(clearance_large=0.0, clearance_small=0.0))
    wide = layout_double_sided(
        FIXT, dowels=DowelSpec(clearance_large=0.4, clearance_small=0.4))
    for (bx, by, bd), (wx, wy, wd) in zip(base.align_holes, wide.align_holes):
        assert abs(bx - wx) < 1e-9 and abs(by - wy) < 1e-9   # centre unchanged
        assert abs(wd - bd - 0.4) < 1e-9                     # hole grew by clearance


def test_double_sided_honours_gcode_backend(tmp_path):
    """Double-sided export must follow the selected machine, not hardcode RML."""
    from gerber2rml.doublesided import build_double_sided
    written = build_double_sided(FIXT, tmp_path, name="ds",
                                 machine="Roland SRM-20 (G-code)")
    names = {p.name for p in written}
    for n in ("ds_align.nc", "ds_bottom_traces.nc", "ds_top_traces.nc", "ds_cutout.nc"):
        assert n in names
    assert not any(p.suffix == ".rml" for p in written)
    nc = (tmp_path / "ds_top_traces.nc").read_text()
    assert nc.startswith("%") and "G54" in nc and nc.rstrip().endswith("%")


# ---- fiducial registration -----------------------------------------------

from gerber2rml.doublesided import FiducialSpec, nominal_top_fiducials


def test_fiducial_count_and_onboard_inside_outline():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4, placement="onboard",
                                                     edge_offset=3.0))
    assert len(lay.align_holes) == 4
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    for (x, y, d) in lay.align_holes:
        assert ox0 - 1e-6 <= x <= ox1 + 1e-6        # inside the board
        assert oy0 - 1e-6 <= y <= oy1 + 1e-6
        assert abs(d - 0.8) < 1e-6


def test_fiducial_waste_outside_outline():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4, placement="waste",
                                                     edge_offset=5.0))
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    xs = [h[0] for h in lay.align_holes]
    ys = [h[1] for h in lay.align_holes]
    assert min(xs) < ox0 and max(xs) > ox1          # corners straddle the board
    assert min(ys) < oy0 and max(ys) > oy1


def test_fiducial_count_two_is_diagonal():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=2, placement="onboard"))
    assert len(lay.align_holes) == 2
    (ax, ay, _), (bx, by, _) = lay.align_holes
    assert ax != bx and ay != by                    # opposite corners, not an edge


def test_nominal_top_fiducials_are_reflected():
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4))
    nom = nominal_top_fiducials(lay)
    for (hx, hy, _), (nx, ny) in zip(lay.align_holes, nom):
        assert abs(nx - (2 * lay.flip_pos - hx)) < 1e-6 and abs(ny - hy) < 1e-6


def test_dowel_still_default():
    lay = layout_double_sided(FIXT)                  # no registration kwarg
    assert len(lay.align_holes) == 2                 # unchanged dowel behaviour


from gerber2rml.doublesided import build_double_sided, build_top_traces


def test_fiducial_build_writes_files_and_runplan(tmp_path):
    files = build_double_sided(FIXT, tmp_path, "fid", registration="fiducial",
                               fiducials=FiducialSpec(count=4))
    names = {p.name for p in files}
    assert "fid_align.nc" in names and "fid_runplan.txt" in names
    plan = (tmp_path / "fid_runplan.txt").read_text(encoding="utf-8")
    assert "fiducial" in plan.lower()
    assert "X" in plan and "Y" in plan          # nominal probe coords listed


def test_fiducial_align_drill_is_stock_only(tmp_path):
    """Fiducial align holes go through the stock + small breakthrough, NOT the
    dowel ~5 mm bed bite."""
    build_double_sided(FIXT, tmp_path, "fid", registration="fiducial",
                       fiducials=FiducialSpec(count=4, breakthrough=0.3),
                       board_thickness=1.6)
    plan = (tmp_path / "fid_runplan.txt").read_text(encoding="utf-8")
    assert "1.90" in plan or "1.9" in plan       # 1.6 + 0.3, no bed bite


def test_fiducial_top_traces_apply_measured_transform(tmp_path):
    lay = layout_double_sided(FIXT, registration="fiducial",
                              fiducials=FiducialSpec(count=4))
    nom = nominal_top_fiducials(lay)
    measured = [(x + 1.0, y + 0.5) for (x, y) in nom]   # pure 1.0/0.5 shift
    out = build_top_traces(FIXT, tmp_path, "fid", registration="fiducial",
                           fiducials=FiducialSpec(count=4),
                           measured_fiducials=measured)
    shifted = out.read_text()
    base = build_top_traces(FIXT, tmp_path, "base", registration="fiducial",
                            fiducials=FiducialSpec(count=4))
    assert shifted != base.read_text()          # transform changed the output
