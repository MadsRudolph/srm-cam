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


def test_header_text_never_nests_parentheses():
    # ( and ) delimit an NC comment, so one inside the text ends the comment
    # early and VPanel reads the rest of the line as words -> "fault". The job
    # name comes from a folder the operator chose, so it can hold anything.
    nc = render(_ring(), xy_feed=4.0, plunge_feed=1.0,
                header=["buck (v2) - step 1 of 4", "2 offset(s), 0.15 mm"])
    for line in nc.splitlines():
        if line.startswith("("):
            assert line.count("(") == 1 and line.count(")") == 1, line
            assert line.endswith(")")
    assert "( buck [v2] - step 1 of 4 )" in nc
    assert "( 2 offset[s], 0.15 mm )" in nc


def test_every_comment_in_a_real_traces_file_is_balanced():
    # The regression: only the traces file carried "offset(s)", so only the
    # traces file faulted in VPanel.
    import tempfile, pathlib, re
    from gerber2rml.cli import build_jobs
    out = pathlib.Path(tempfile.mkdtemp())
    build_jobs("tests/fixtures/mosfet_test", out, "buck (v2)")
    for p in sorted(out.glob("*.nc")):
        for line in p.read_text().splitlines():
            if "(" in line or ")" in line:
                assert re.fullmatch(r"\([^()]*\)", line.strip()), f"{p.name}: {line}"


def _motion(nc):
    return [l for l in nc.splitlines() if l.startswith(("G0 ", "G1 "))]


def test_a_job_crosses_at_the_top_and_only_then_lowers():
    """A student's report: the job dropped to travel height wherever the head
    was and then crossed, through the clamps and the fixture."""
    nc = render([[Move(10, 20, 2.0, rapid=True), Move(10, 20, -0.1),
                  Move(15, 20, -0.1)]], xy_feed=4.0, plunge_feed=1.0)
    lines = nc.splitlines()
    assert _motion(nc)[:2] == ["G0 X10. Y20.", "G0 Z2."]
    assert lines.index("G28 Z0.") < lines.index("G0 X10. Y20.")


def test_a_job_that_opens_on_a_cut_also_crosses_first():
    nc = render([[Move(10, 20, -0.1), Move(15, 20, -0.1)]],
                xy_feed=4.0, plunge_feed=1.0)
    assert _motion(nc)[0] == "G0 X10. Y20."


def test_a_rapid_climbs_before_it_crosses_and_crosses_before_it_lowers():
    nc = render([[Move(0, 0, 2.0, rapid=True), Move(0, 0, -0.1),
                  Move(5, 0, 1.0, rapid=True), Move(9, 0, 0.5, rapid=True)]],
                xy_feed=4.0, plunge_feed=1.0)
    m = _motion(nc)
    climb = m.index("G0 Z1.")
    assert m[climb + 1] == "G0 X5. Y0."
    assert m[climb + 2:climb + 4] == ["G0 X9. Y0.", "G0 Z0.5"]
