"""Tests for the SRM-20 G-code (NC) backend header/spindle sequence."""
from gerber2rml.backends.gcode import render, DEFAULT_SPINUP_S
from gerber2rml.toolpath import Move


def _ring():
    return [[Move(0, 0, 2.0, rapid=True), Move(0, 0, -0.1),
             Move(5, 0, -0.1), Move(0, 0, 2.0, rapid=True)]]


def test_spinup_dwell_emitted_after_spindle_on():
    # The SRM-20's M3 does not wait for the spindle to reach speed (manual p.116),
    # so we hold with a G04 dwell before any cutting to avoid a torque spike when
    # the bit engages copper at part-RPM.
    nc = render(_ring(), xy_feed=4.0, plunge_feed=1.0).splitlines()
    i_m3 = nc.index("M3")
    dwell = [j for j, ln in enumerate(nc) if ln.startswith("G04")]
    assert dwell, "expected a G04 dwell in the header"
    assert dwell[0] > i_m3, "dwell must come after the spindle is turned on"
    # SRM-20 has no P word; dwell time is X<seconds>
    assert nc[dwell[0]] == f"G04 X{DEFAULT_SPINUP_S:g}."


def test_dwell_is_before_the_first_motion():
    nc = render(_ring(), xy_feed=4.0, plunge_feed=1.0).splitlines()
    i_dwell = [j for j, ln in enumerate(nc) if ln.startswith("G04")][0]
    i_first_g0 = next(j for j, ln in enumerate(nc) if ln.startswith("G0 "))
    assert i_dwell < i_first_g0


def test_spinup_seconds_configurable():
    nc = render(_ring(), xy_feed=4.0, plunge_feed=1.0, spinup_s=3.5)
    assert "G04 X3.5" in nc


def test_zero_spinup_omits_the_dwell():
    nc = render(_ring(), xy_feed=4.0, plunge_feed=1.0, spinup_s=0.0)
    assert "G04" not in nc
