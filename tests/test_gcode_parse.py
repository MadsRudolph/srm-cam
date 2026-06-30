"""Round-trip tests: render toolpaths to a file, parse them back."""
from gerber2rml.toolpath import Move
from gerber2rml.backends import srm20, gcode
from gerber2rml.engine.gcode_parse import parse_nc, parse_rml, parse_file


def _square_ring():
    return [[Move(0, 0, 2.0, rapid=True), Move(0, 0, -0.15),
             Move(10, 0, -0.15), Move(10, 10, -0.15), Move(0, 10, -0.15),
             Move(0, 0, -0.15), Move(0, 0, 2.0, rapid=True)]]


def _cut_xy(toolpaths):
    return {(round(m.x, 2), round(m.y, 2))
            for tp in toolpaths for m in tp if not m.rapid}


def test_nc_round_trip_recovers_cut_points():
    tps = _square_ring()
    nc = gcode.render(tps, xy_feed=4.0, plunge_feed=1.0)
    parsed = parse_nc(nc)
    assert parsed, "expected a parsed toolpath"
    pts = _cut_xy(parsed)
    for corner in [(0, 0), (10, 0), (10, 10), (0, 10)]:
        assert corner in pts


def test_nc_skips_homing_moves():
    # G28 homing lines must not appear as toolpath points
    nc = gcode.render(_square_ring(), xy_feed=4.0, plunge_feed=1.0)
    assert "G28" in nc                       # the file does home
    parsed = parse_nc(nc)
    zs = [round(m.z, 3) for tp in parsed for m in tp]
    assert all(z <= 2.0 + 1e-6 for z in zs)  # no machine-home Z jump captured


def test_parse_skips_dwell_line():
    # A G04 dwell carries an X<seconds> arg that must NOT be read as an X coord.
    nc = "\n".join(["%", "O0001", "G90 G21", "M3", "G04 X2.",
                    "G0 X0. Y0.", "G1 Z-0.1 F60.", "G1 X5. Y0. F240.", "M30", "%"])
    pts = [(m.x, m.y) for m in parse_nc(nc)[0]]
    assert (2.0, 0.0) not in pts             # the dwell's X2. is not a move
    assert (5.0, 0.0) in pts                  # the real cut still parses


def test_nc_marks_rapid_vs_cut():
    nc = gcode.render(_square_ring(), xy_feed=4.0, plunge_feed=1.0)
    parsed = parse_nc(nc)[0]
    assert any(m.rapid for m in parsed)       # G0 rapids
    assert any(not m.rapid for m in parsed)   # G1 cuts


def test_rml_round_trip_recovers_cut_points():
    tps = _square_ring()
    rml = srm20.render(tps, xy_feed=4.0, plunge_feed=1.0)
    parsed = parse_rml(rml)
    assert parsed
    pts = _cut_xy(parsed)
    for corner in [(0, 0), (10, 0), (10, 10), (0, 10)]:
        assert corner in pts


def test_rml_rapid_detection():
    # backend brackets rapids with equal VS/!VZ, cuts with differing feeds
    rml = srm20.render(_square_ring(), xy_feed=4.0, plunge_feed=1.0)
    parsed = parse_rml(rml)[0]
    assert parsed[0].rapid                    # first move is the rapid approach
    assert any(not m.rapid for m in parsed)   # the ring cuts are feeds


def test_parse_file_dispatches_by_extension(tmp_path):
    tps = _square_ring()
    nc = tmp_path / "board_traces.nc"
    nc.write_text(gcode.render(tps, 4.0, 1.0))
    rml = tmp_path / "board_traces.rml"
    rml.write_text(srm20.render(tps, 4.0, 1.0))
    assert _cut_xy(parse_file(nc)) >= {(0, 0), (10, 0)}
    assert _cut_xy(parse_file(rml)) >= {(0, 0), (10, 0)}


def test_empty_text_parses_to_nothing():
    assert parse_nc("") == []
    assert parse_rml("") == []
