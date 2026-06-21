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
