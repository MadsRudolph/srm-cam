from pathlib import Path
from gerber2rml.doublesided import (
    layout_double_sided, preview_layout_double_sided, reflect_x,
    DowelSpec, PIN_LARGE, PIN_SMALL,
)

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
    assert abs(bx - lay.x_axis) < 1e-6 and abs(tx - lay.x_axis) < 1e-6
    _x0, y0, _x1, y1 = lay.outline.bounds
    assert by < y0 and ty > y1                 # one below the board, one above
    # keyed: large below, small above, and the two differ
    assert abs(bd - PIN_LARGE) < 1e-6 and abs(td - PIN_SMALL) < 1e-6
    assert abs(bd - td) > 0.5
    # the pins hug the edges (offset ~ edge_offset), NOT 50 mm out in bare bed
    assert (y0 - by) < 12.0 and (ty - y1) < 12.0


def test_top_outline_reflected_about_vertical_axis():
    lay = layout_double_sided(FIXT)
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    tx0, ty0, tx1, ty1 = lay.top_outline.bounds
    assert abs(oy0 - ty0) < 1e-6 and abs(oy1 - ty1) < 1e-6      # Y preserved
    assert abs(((ox0 + ox1) / 2) - lay.x_axis) < 1e-6          # board centred on axis
    assert abs(((tx0 + tx1) / 2) - lay.x_axis) < 1e-6          # reflected copy too


def test_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT)
    (hx, hy, hd) = lay.holes[0]
    assert any(abs(rx - (2 * lay.x_axis - hx)) < 1e-6 and abs(ry - hy) < 1e-6
               for (rx, ry, rd) in reflect_x(lay.holes, lay.x_axis))


# ---- grid-seated dowels --------------------------------------------------

def test_grid_pins_land_on_grid_holes_and_are_keyed_by_spacing():
    spec = DowelSpec(mode="grid", pitch_x=14.2, pitch_y=14.2, grid_pin=4.0)
    lay = layout_double_sided(FIXT, dowels=spec)
    (bx, by, bd), (tx, ty, td) = lay.align_holes
    # both on the same grid column (= the flip axis), and that column is a
    # multiple of the pitch from the datum hole at the origin
    assert abs(bx - lay.x_axis) < 1e-6 and abs(tx - lay.x_axis) < 1e-6
    assert abs(round(lay.x_axis / 14.2) - lay.x_axis / 14.2) < 1e-6
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
    assert any(n.startswith("ds_bottom_drill_") and n.endswith("mm.rml") for n in names)
    for p in written:
        if p.suffix == ".rml":
            t = p.read_text()
            assert t.startswith("^IN;!MC1;") and t.rstrip().endswith("!MC0;^IN;")


def test_grid_mode_build_and_runplan(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    written = build_double_sided(FIXT, tmp_path, name="g", machine="Roland SRM-20",
                                 dowels=DowelSpec(mode="grid"))
    names = {p.name for p in written}
    for n in ("g_align.rml", "g_bottom_traces.rml", "g_top_traces.rml", "g_cutout.rml"):
        assert n in names
    plan = (tmp_path / "g_runplan.txt").read_text()
    assert "grid" in plan.lower() and "datum grid hole" in plan


def _deepest_z(path):
    zs = [int(line.split(",")[2].rstrip(";")) for line in path.read_text().splitlines()
          if line.startswith("Z")]
    return min(zs)


def test_align_drills_deeper_than_board_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import DrillJob
    written = build_double_sided(FIXT, tmp_path, name="d", machine="Roland SRM-20",
                                 drill=DrillJob(), align_depth=6.0)
    bottom_drills = [p for p in written if p.name.startswith("d_bottom_drill_")]
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
    assert abs(lay.align_holes[0][0] - lay.x_axis) < 1e-6
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
    spec = DowelSpec(pin_clearance=0.2)
    only = build_align_only(FIXT, tmp_path / "only", "b", dowels=spec,
                            machine="Roland SRM-20 (G-code)")
    assert [p.name for p in (tmp_path / "only").iterdir()] == ["b_align.nc"]
    full = build_double_sided(FIXT, tmp_path / "full", "b", dowels=spec,
                              machine="Roland SRM-20 (G-code)")
    align_full = next(p for p in full if p.name == "b_align.nc")
    assert only.read_text() == align_full.read_text()


def test_pin_clearance_widens_holes_without_moving_centres():
    """Bumping pin_clearance grows the milled hole but leaves the dowel centre
    (and the whole placement) put, so a re-cut registers on the existing hole."""
    base = layout_double_sided(FIXT, dowels=DowelSpec(pin_clearance=0.0))
    wide = layout_double_sided(FIXT, dowels=DowelSpec(pin_clearance=0.4))
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
