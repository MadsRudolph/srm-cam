import re
import pytest
from gerber2rml.engine.testcard import feed_ladder_card, render_feed_ladder


def test_card_paths_and_feeds_align():
    paths, feeds, bbox = feed_ladder_card()
    assert len(paths) == len(feeds)
    assert set(feeds) == {4.0, 6.0, 8.0, 10.0, 12.0, 15.0}
    x0, y0, x1, y1 = bbox
    assert x0 < x1 and y0 < y1
    for tp in paths:
        for m in tp:
            assert x0 <= m.x <= x1 and y0 <= m.y <= y1


def test_card_cuts_at_trace_depth_only():
    paths, _feeds, _ = feed_ladder_card(cut_depth=0.15, travel_z=1.0)
    zs = {round(m.z, 3) for tp in paths for m in tp}
    assert zs == {-0.15, 1.0}                    # cut plane + travel, nothing else


def test_render_emits_one_f_word_per_feed_step():
    text, bbox = render_feed_ladder()
    # mm/s -> mm/min: 4->240, 6->360, 8->480, 10->600, 12->720, 15->900
    for fpm in (240, 360, 480, 600, 720, 900):
        assert f"F{fpm}." in text, f"missing F{fpm}."
    assert text.startswith("%")
    assert "M30" in text
    # every cut coordinate stays inside the card bbox
    x0, y0, x1, y1 = bbox
    for mx in re.finditer(r"G1 X(-?\d+\.?\d*) Y(-?\d+\.?\d*)", text):
        assert x0 - 1e-6 <= float(mx.group(1)) <= x1 + 1e-6
        assert y0 - 1e-6 <= float(mx.group(2)) <= y1 + 1e-6


def test_render_refuses_rml_backend():
    with pytest.raises(ValueError):
        render_feed_ladder(machine="Roland SRM-20")


def test_gcode_xy_feeds_validation():
    from gerber2rml.backends.gcode import render
    from gerber2rml.toolpath import Move
    tp = [[Move(0, 0, 1, rapid=True), Move(0, 0, -0.1), Move(1, 0, -0.1),
           Move(1, 0, 1, rapid=True)]]
    with pytest.raises(ValueError):
        render(tp, xy_feed=4.0, plunge_feed=1.0, xy_feeds=[4.0, 6.0])
    out = render(tp, xy_feed=4.0, plunge_feed=1.0, xy_feeds=[9.0])
    assert "F540." in out                        # 9 mm/s -> 540 mm/min
