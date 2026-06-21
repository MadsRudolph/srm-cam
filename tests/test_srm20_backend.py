from gerber2rml.toolpath import Move
from gerber2rml.backends.srm20 import render


def test_scale_is_40_units_per_mm():
    rml = render([[Move(20.0, 0.0, -0.1)]], xy_feed=4.0, plunge_feed=1.0)
    assert "Z800,0,-4;" in rml          # 20 mm * 40 = 800 ; -0.1 mm * 40 = -4


def test_spindle_is_turned_on_then_off():
    rml = render([[Move(0, 0, 2.0, rapid=True)]], xy_feed=4.0, plunge_feed=1.0)
    lines = rml.splitlines()
    assert lines[0].startswith("^IN;!MC1;")     # header MUST enable spindle
    assert "!MC0" not in lines[0]               # the legacy header bug
    assert lines[-1] == "!MC0;^IN;"             # footer disables + resets


def test_feeds_emitted_for_cut_moves():
    rml = render([[Move(1, 1, -0.1)]], xy_feed=4.0, plunge_feed=1.0)
    assert "VS4.0;!VZ1.0;" in rml


def test_rapid_uses_rapid_feed():
    rml = render([[Move(0, 0, 2.0, rapid=True)]], xy_feed=4.0, plunge_feed=1.0,
                 rapid_feed=15.0)
    # rapids set both XY and Z (retract) speed to the rapid feed
    assert "VS15.0;!VZ15.0;" in rml
