"""Names and setup values from outside the app cannot reach the machine raw."""
import math

from gerber2rml.backends.gcode import _c
from gerber2rml.backends.srm20 import render
from gerber2rml.config import TraceJob, CutoutJob, checked_job
from gerber2rml.naming import clean_name
from gerber2rml.toolpath import Move


def test_a_newline_cannot_end_a_gcode_comment():
    line = _c("lab\nG90 G1 Z-20 F600\nX0 Y0\n(")
    assert "\n" not in line and line.startswith("( ") and line.endswith(" )")
    assert line.count("(") == 1 and line.count(")") == 1


def test_names_cannot_leave_the_export_folder():
    for bad in ("..\\..\\x", "../x", "a:b*c?", "\n", "  .hidden"):
        s = clean_name(bad)
        assert ".." not in s and "/" not in s and "\\" not in s
        assert ":" not in s and "\n" not in s and not s.startswith(".")
    assert clean_name("") == "board"
    assert clean_name("Mads_rødt kort-2") == "Mads_rødt kort-2"


def test_setup_values_out_of_range_are_refused_not_kept():
    job, refused = checked_job(CutoutJob(), {"travel_z": -1.0, "total_depth": 1.6,
                                             "xy_feed": float("nan"),
                                             "nonsense": 3})
    assert job.travel_z == CutoutJob().travel_z
    assert job.total_depth == 1.6
    assert math.isfinite(job.xy_feed)
    assert set(refused) == {"travel_z", "xy_feed", "nonsense"}
    job, refused = checked_job(TraceJob(), {"cut_depth": 3.5, "tool_type": "x",
                                            "offsets": 3})
    assert job.offsets == 3 and set(refused) == {"cut_depth", "tool_type"}


def test_rml_lifts_before_it_travels_and_can_set_the_speed():
    paths = [[Move(10, 10, 2, rapid=True), Move(10, 10, -0.1), Move(20, 10, -0.1)]]
    rml = render(paths, xy_feed=4, plunge_feed=1, rpm=7000, safe_start=True)
    lines = rml.splitlines()
    assert lines[0] == "^IN;!RC7000;!MC1;"
    lift = next(l for l in lines if l.startswith("!PZ"))
    assert lift == "!PZ0,200;PU1000,1000;"
    assert lines.index(lift) < next(i for i, l in enumerate(lines)
                                    if l.startswith("Z"))


def test_the_suite_never_writes_the_real_settings():
    # QSettings("org", "app") is always the registry on Windows, whatever
    # the default format says - which let the suite write the operator's
    # remembered folders and Automatic mode's bracket corner and copper
    # height into the real app. Every SRM-CAM settings store must follow
    # the default format, so the conftest's INI redirect catches it.
    from PySide6.QtCore import QSettings
    from gerber2rml.gui2 import tier, workspace
    for s in (workspace._settings(), tier._settings()):
        assert s.format() == QSettings.IniFormat, s.fileName()
