from pathlib import Path
from gerber2rml.doublesided import layout_double_sided, reflect_y

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_reflect_y_fixes_axis():
    assert reflect_y([(5.0, 10.0, 0.8)], y_axis=10.0)[0][1] == 10.0
    assert reflect_y([(5.0, 12.0, 0.8)], y_axis=10.0)[0][1] == 8.0

def test_layout_has_two_align_holes_on_axis():
    lay = layout_double_sided(FIXT, pin_diameter=3.0, margin=6.0)
    assert len(lay.align_holes) == 2
    assert abs(lay.align_holes[0][1] - lay.y_axis) < 1e-6
    assert abs(lay.align_holes[1][1] - lay.y_axis) < 1e-6
    bx0, _by0, bx1, _by1 = lay.outline.bounds
    assert lay.align_holes[0][0] < bx0 and lay.align_holes[1][0] > bx1
    assert lay.align_holes[1][0] - lay.align_holes[0][0] >= 104.0   # beyond the 104 box
    assert lay.align_holes[0][0] > 0                                # positive quadrant
    assert all(abs(d - 3.0) < 1e-6 for (_x, _y, d) in lay.align_holes)

def test_through_hole_registers_after_flip():
    lay = layout_double_sided(FIXT, pin_diameter=3.0, margin=6.0)
    (hx, hy, hd) = lay.holes[0]
    assert any(abs(rx - hx) < 1e-6 and abs(ry - (2 * lay.y_axis - hy)) < 1e-6
               for (rx, ry, rd) in reflect_y(lay.holes, lay.y_axis))


def test_build_double_sided_writes_jobs(tmp_path):
    from gerber2rml.doublesided import build_double_sided
    from gerber2rml.config import TraceJob, DrillJob, CutoutJob
    written = build_double_sided(FIXT, tmp_path, name="ds",
                                 trace=TraceJob(), drill=DrillJob(), cutout=CutoutJob())
    names = {p.name for p in written}
    for n in ("ds_align.rml", "ds_bottom_drill.rml", "ds_bottom_traces.rml",
              "ds_top_traces.rml", "ds_cutout.rml"):
        assert n in names
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
    build_double_sided(FIXT, tmp_path, name="d", drill=DrillJob(), align_depth=6.0)
    # align holes must go deeper (more negative Z) than the board's own holes,
    # to anchor the dowel pins in the sacrificial bed
    assert _deepest_z(tmp_path / "d_align.rml") < _deepest_z(tmp_path / "d_bottom_drill.rml")

def test_bottom_drill_excludes_alignment_holes(tmp_path):
    from gerber2rml.doublesided import build_double_sided, layout_double_sided
    lay = layout_double_sided(FIXT)
    build_double_sided(FIXT, tmp_path, name="d")
    text = (tmp_path / "d_bottom_drill.rml").read_text()
    ax, ay, _d = lay.align_holes[0]
    token = f"Z{round(ax * 40)},{round(ay * 40)},"   # 40 RML units/mm
    assert token not in text          # pinned alignment hole is NOT re-drilled
