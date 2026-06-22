from pathlib import Path
from gerber2rml.doublesided import layout_double_sided, reflect_x

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_reflect_x_fixes_axis():
    assert reflect_x([(10.0, 5.0, 0.8)], x_axis=10.0)[0][0] == 10.0
    assert reflect_x([(12.0, 5.0, 0.8)], x_axis=10.0)[0][0] == 8.0

def test_flip_axis_is_vertical_pins_above_and_below():
    lay = layout_double_sided(FIXT, pin_diameter=3.0, margin=6.0)
    assert len(lay.align_holes) == 2
    # both pins lie on the vertical flip axis (same x)
    assert abs(lay.align_holes[0][0] - lay.x_axis) < 1e-6
    assert abs(lay.align_holes[1][0] - lay.x_axis) < 1e-6
    _bx0, by0, _bx1, by1 = lay.outline.bounds
    # one pin below the board, one above
    assert lay.align_holes[0][1] < by0 and lay.align_holes[1][1] > by1
    # span beyond the 104 box, positive quadrant, 3 mm pins
    assert lay.align_holes[1][1] - lay.align_holes[0][1] >= 104.0
    assert lay.align_holes[0][1] > 0
    assert all(abs(d - 3.0) < 1e-6 for (_x, _y, d) in lay.align_holes)

def test_top_outline_reflected_about_vertical_axis():
    # A vertical flip preserves the Y extent and mirrors X about the axis.
    # This is what makes the top come out as the plain (un-rotated) F.Cu.
    lay = layout_double_sided(FIXT)
    ox0, oy0, ox1, oy1 = lay.outline.bounds
    tx0, ty0, tx1, ty1 = lay.top_outline.bounds
    assert abs(oy0 - ty0) < 1e-6 and abs(oy1 - ty1) < 1e-6      # Y preserved
    assert abs(((ox0 + ox1) / 2) - lay.x_axis) < 1e-6           # board centred on axis
    assert abs(((tx0 + tx1) / 2) - lay.x_axis) < 1e-6           # reflected copy too

def test_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT)
    (hx, hy, hd) = lay.holes[0]
    assert any(abs(rx - (2 * lay.x_axis - hx)) < 1e-6 and abs(ry - hy) < 1e-6
               for (rx, ry, rd) in reflect_x(lay.holes, lay.x_axis))


def test_build_double_sided_writes_jobs(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob
    written = build_double_sided(FIXT, tmp_path, name="ds",
                                 trace=TraceJob(), drill=DrillJob(), cutout=CutoutJob())
    names = {p.name for p in written}
    for n in ("ds_align.rml", "ds_bottom_traces.rml", "ds_top_traces.rml",
              "ds_cutout.rml"):
        assert n in names
    # bottom drill is split per diameter
    assert any(n.startswith("ds_bottom_drill_") and n.endswith("mm.rml") for n in names)
    for p in written:
        if p.suffix == ".rml":
            t = p.read_text()
            assert t.startswith("^IN;!MC1;") and t.rstrip().endswith("!MC0;^IN;")

def _deepest_z(path):
    zs = [int(line.split(",")[2].rstrip(";")) for line in path.read_text().splitlines()
          if line.startswith("Z")]
    return min(zs)

def test_align_drills_deeper_than_board_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import DrillJob
    written = build_double_sided(FIXT, tmp_path, name="d", drill=DrillJob(), align_depth=6.0)
    bottom_drills = [p for p in written if p.name.startswith("d_bottom_drill_")]
    # align holes must go deeper (more negative Z) than every board-hole file
    deepest_board = min(_deepest_z(p) for p in bottom_drills)
    assert _deepest_z(tmp_path / "d_align.rml") < deepest_board

def test_bottom_drill_excludes_alignment_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided, layout_double_sided
    lay = layout_double_sided(FIXT)
    written = build_double_sided(FIXT, tmp_path, name="d")
    ax, ay, _d = lay.align_holes[0]
    token = f"Z{round(ax * 40)},{round(ay * 40)},"   # 40 RML units/mm
    for p in written:
        if p.name.startswith("d_bottom_drill_"):
            assert token not in p.read_text()    # pinned hole is never re-drilled

def test_preview_layout_registers_layers_on_holes():
    # The preview lays both copper layers in the same design frame, so a through-
    # hole has copper (a pad) on BOTH layers at its centre — i.e. they register
    # and the holes land on the pads (unlike the mirror-imaged machine frame).
    from gerber2rml.doublesided import preview_layout_double_sided
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
    written = build_double_sided(FIXT, tmp_path, name="d",
                                 drill=DrillJob(single_bit=True, bit_diameter=0.8))
    drills = sorted(p.name for p in written if "_bottom_drill" in p.name)
    assert drills == ["d_bottom_drill.rml"]


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
