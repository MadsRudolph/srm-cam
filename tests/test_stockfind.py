"""Finding the stock, running a job and knowing it ended - on the simulator."""
import threading

import pytest

from gerber2rml.backends.srm20 import render
from gerber2rml.engine import simmachine as sm
from gerber2rml.engine import spi_probe, stockfind
from gerber2rml.engine.fidfind import hole_test
from gerber2rml.engine.runner import JobRunner, RunStopped, program_end
from gerber2rml.engine.rmlspool import find_mill
from gerber2rml.toolpath import Move


def _sim(**kw):
    kw.setdefault("speedup", 5000)
    kw.setdefault("size", (100000, 80000))
    kw.setdefault("corner", (41300, 27800))
    m = sm.machine(**kw)
    return m, spi_probe.open_link("SIM")


@pytest.mark.parametrize("corner,angle", [((41300, 27800), 1.2),
                                          ((15000, 40000), -2.5),
                                          ((60000, 10000), 0.0)])
def test_the_stock_is_found_where_it_lies(corner, angle):
    m, ser = _sim(corner=corner, angle_deg=angle)
    p = stockfind.find_stock(ser, (corner[0] / 1000 + 45, corner[1] / 1000 + 40),
                             (100, 80))
    assert abs(p.x - corner[0] / 1000) < 0.1
    assert abs(p.y - corner[1] / 1000) < 0.1
    assert abs(p.angle - angle) < 0.05
    assert abs(p.z - m.surface_z / 1000) < 0.1


def test_a_wrong_size_stops_the_run():
    _m, ser = _sim()
    with pytest.raises(stockfind.StockNotFound, match="not 120.0") as e:
        stockfind.find_stock(ser, (90, 70), (120, 80), measure=True)
    w, h = e.value.measured                  # and it says what it is
    assert abs(w - 100) < 0.2 and abs(h - 80) < 0.2


def test_a_click_off_the_stock_says_so():
    _m, ser = _sim()
    with pytest.raises(stockfind.StockNotFound, match="no copper"):
        stockfind.find_stock(ser, (10, 10), (100, 80))


def test_a_job_runs_to_its_end_and_drills_what_it_says():
    m, ser = _sim()
    z = stockfind.seek_surface(ser, 80000, 60000)
    spi_probe.set_origin(ser, 0, 0, z)
    printer = sm.printer()
    import math
    # A 1.6 mm hole with the 0.8 mm bit: the probe bit can only drop into a
    # hole wider than itself, which is why fiducials are bit + 0.8 mm.
    ring = [Move(80 + 0.4 * math.cos(a / 8 * math.pi),
                 60 + 0.4 * math.sin(a / 8 * math.pi), -2.0) for a in range(17)]
    rml = render([[Move(80.4, 60, 2, rapid=True)] + ring +
                  [Move(80.4, 60, 2, rapid=True), Move(90, 60, 2, rapid=True)]],
                 4, 1)
    assert program_end(rml) == (9000, 6000)
    JobRunner(ser, printer, lambda: False, still_s=0.05, poll_s=0.01).run(
        rml, "drill")
    stockfind.reference_at(ser, 85000, 60000, surface_um=z)
    assert hole_test(ser, 80000, 60000) is False
    assert hole_test(ser, 81500, 60000) is True


def test_stop_purges_the_job_and_raises():
    m, ser = _sim(speedup=2)
    printer = sm.printer()
    stop = threading.Event()
    rml = render([[Move(20, 20, 2, rapid=True), Move(150, 120, 2, rapid=True)]],
                 4, 1)
    threading.Timer(0.2, stop.set).start()
    with pytest.raises(RunStopped):
        JobRunner(ser, printer, stop.is_set, still_s=0.05, poll_s=0.01).run(
            rml, "long")
    assert printer.pending() == 0


def test_the_mill_printer_is_recognised_by_name():
    assert find_mill(["Adobe PDF", "Roland SRM-20"]) == "Roland SRM-20"
    assert find_mill(["Adobe PDF"]) is None


def test_fixture_rows_find_the_stock_and_never_reach_far_past_an_edge():
    # The stock in a fixture: walks only where the operator says, the guess
    # a couple of mm off, and no walk more than one step past the copper.
    m, ser = _sim(corner=(30000, 20000), angle_deg=0.6, size=(160000, 100000))
    reach = []
    real = stockfind.hole_test

    def watched(s, x, y, **kw):
        u, v = m.to_stock(x, y)
        reach.append(max(-u, -v))
        return real(s, x, y, **kw)
    stockfind.hole_test = watched
    try:
        rows = {"corner": (28.0, 22.0), "left": (12.0, 40.0),
                "front": (55.0, 90.0), "start": (70.0, 30.0)}
        p = stockfind.find_stock(ser, (0, 0), (160, 100), rows=rows,
                                 checks=((155.0, 75.0), (40.0, 95.0)))
    finally:
        stockfind.hole_test = real
    assert abs(p.x - 30) < 0.1 and abs(p.y - 20) < 0.1
    assert abs(p.angle - 0.6) < 0.05
    assert max(reach) / 1000 < 2.5       # one 2 mm step + the bit radius


def test_a_stock_smaller_than_typed_stops_without_walking_outside():
    _m, ser = _sim()
    with pytest.raises(stockfind.StockNotFound, match="no copper at"):
        stockfind.find_stock(ser, (90, 70), (120, 80))


@pytest.mark.parametrize("corner", stockfind.CORNERS)
def test_a_stock_in_a_corner_bracket_is_one_touch(corner):
    m, ser = _sim(corner=(40000, 30000), angle_deg=0.0, size=(120000, 80000))
    datum = {"front-left": (40, 30), "back-left": (40, 110),
             "front-right": (160, 30), "back-right": (160, 110)}[corner]
    p = stockfind.from_datum(ser, datum, corner, (120, 80))
    assert (p.x, p.y, p.angle) == (40, 30, 0.0)
    assert abs(p.z - m.surface_z / 1000) < 0.1


def test_a_mill_that_stopped_away_from_the_end_does_not_hang_the_run():
    m, ser = _sim()
    said = []
    rml = render([[Move(80, 60, 2, rapid=True), Move(90, 60, 2, rapid=True)]], 4, 1)
    assert JobRunner(ser, sm.printer(), lambda: False, note=said.append,
                     still_s=0.05, poll_s=0.01, settled_s=0.2).run(
        rml, "traces", end_mm=(150.0, 96.0), timeout_s=10)
    assert "not at the program's end" in said[-1] and "150.00" in said[-1]


def test_a_slow_job_is_not_taken_for_a_stopped_one():
    m, ser = _sim()
    said = []
    m.speedup = 20.0                       # about 0.1 s for each mm here
    rml = render([[Move(80, 60, 2, rapid=True), Move(90, 60, 2, rapid=True)]], 4, 1)
    JobRunner(ser, sm.printer(), lambda: False, note=said.append,
              still_s=0.05, poll_s=0.01, settled_s=0.5).run(rml, "traces",
                                                            timeout_s=30)
    assert not said


def _probe_port(pos_z_um, speedup=1e6):
    m = sm.machine(speedup=speedup, corner=(32020, 27740),
                   size=(160000, 100000))
    m.pos = [100000, 80000, pos_z_um]
    return m, m.surface(100000, 80000), sm.serial_for("SIM")


def test_a_touch_from_the_top_with_a_known_height_drops_fast_and_lands():
    m, surface, ser = _probe_port(0)
    r = stockfind.touch_from_anywhere(ser, surface)
    assert r is not None and r[2] * 1000 == pytest.approx(surface, abs=50)
    assert r[:2] == (100.0, 80.0)


def test_a_touch_from_the_top_with_no_known_height_still_lands():
    m, surface, ser = _probe_port(0)
    r = stockfind.touch_from_anywhere(ser, None)
    assert r is not None and r[2] * 1000 == pytest.approx(surface, abs=50)


def test_a_touch_that_already_reads_contact_goes_no_lower():
    m, surface, ser = _probe_port(0)
    m.pos[2] = surface - 10
    assert stockfind.touch_from_anywhere(ser, None) is None
    assert m.pos[2] == surface - 10


def test_a_hint_never_moves_the_head_up():
    m, surface, ser = _probe_port(0)
    m.pos[2] = surface + 3000
    assert stockfind.drop_to_hint(ser, surface)
    assert m.pos[2] == surface + 3000


def test_a_fast_drop_stops_on_copper_higher_than_it_was_told():
    m, surface, ser = _probe_port(0)
    said = []
    # Told the copper is 20 mm lower than it is: this is a longer bit.
    assert stockfind.drop_to_hint(ser, surface - 20000, note=said.append)
    assert any("higher than expected" in s for s in said)
    assert m.pos[2] >= surface


def test_with_no_known_height_it_still_drops_fast_on_firmware_that_stops():
    m, surface, ser = _probe_port(0)
    said = []
    stockfind.seek_surface(ser, 100000, 80000, note=said.append, hint_um=None)
    assert any("Dropping fast" in s for s in said)
    # One look, not one per 5.5 mm from the top.
    assert sum("Looking for" in s for s in said) <= 2


def test_older_firmware_with_no_known_height_does_not_drop_blind(monkeypatch):
    m, surface, ser = _probe_port(0)
    monkeypatch.setattr(spi_probe, "firmware_version",
                        lambda s, timeout=1.5: (4, {"timedmove"}))
    said = []
    assert stockfind.drop_to_hint(ser, None, note=said.append)
    assert m.pos[2] == 0 and "feeling down" in said[0]
