"""Golden-output regression: the same board must keep producing the same cut.

Every other test in this suite checks a property — that a path is inside the
outline, that a depth is clamped, that a file parses. This one checks the thing
those properties are a proxy for: **byte-for-byte identical machine output** for
a fixed board and a fixed set of job parameters.

Why it exists: the app is shipped as a frozen bundle that will be rebuilt years
from now, on a machine nobody has met, against whatever versions of shapely,
numpy and gerbonara exist then. A geometry library changing its buffer or
union behaviour by a few microns would not fail any property test — it would
just quietly cut a slightly different board. This test turns that class of
silent change into a loud one.

The parameters below are pinned deliberately (not read from ``config.py``
defaults) so this test measures the ENGINE, not the defaults. Changing a
default is a visible edit; changing what the engine does with the same inputs
is not.

When a diff here is expected and correct — a real toolpath improvement — bless
the new output:

    GOLDEN_UPDATE=1 python -m pytest tests/test_golden.py

then READ THE DIFF in ``git diff tests/fixtures/golden/`` before committing it.
If you can't explain a changed line, don't commit it: that is the whole point
of this file.
"""
import os
from pathlib import Path

import pytest

from gerber2rml.cli import build_jobs
from gerber2rml.config import TraceJob, DrillJob, CutoutJob

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
GOLDEN = Path(__file__).parent / "fixtures" / "golden"
UPDATE = os.environ.get("GOLDEN_UPDATE") == "1"

# Pinned job parameters — a realistic single-0.8 mm-bit run. Do not replace
# these with config.py defaults (see the module docstring).
TRACE = TraceJob(bit_diameter=0.8, cut_depth=0.15, offsets=1, stepover=0.5,
                 xy_feed=4.0, plunge_feed=1.0, travel_z=2.0, tool_type="flat")
DRILL = DrillJob(bit_diameter=0.8, single_bit=True, cut_depth=0.6,
                 total_depth=1.7, peck_retract=0.5, xy_feed=4.0,
                 plunge_feed=1.0, travel_z=2.0)
CUTOUT = CutoutJob(bit_diameter=0.8, cut_depth=0.6, total_depth=1.7, tabs=4,
                   tab_width=1.5, xy_feed=4.0, plunge_feed=1.0, travel_z=2.0)


def _build(tmp_path, machine, name):
    return build_jobs(FIXT, tmp_path, name, trace=TRACE, drill=DRILL,
                      cutout=CUTOUT, mirror=True, machine=machine)


@pytest.mark.parametrize("machine, name", [
    ("Roland SRM-20 (G-code)", "golden_gcode"),   # the default export
    ("Roland SRM-20", "golden_rml"),              # the legacy RML path
])
def test_output_matches_golden(tmp_path, machine, name):
    written = _build(tmp_path, machine, name)
    assert written, "build_jobs produced no files"

    GOLDEN.mkdir(parents=True, exist_ok=True)
    for produced in written:
        ref = GOLDEN / produced.name
        got = produced.read_text(encoding="utf-8")
        if UPDATE:
            ref.write_text(got, encoding="utf-8", newline="\n")
            continue
        assert ref.exists(), (
            f"No golden file for {produced.name}. If this output is new and "
            f"correct, run:  GOLDEN_UPDATE=1 python -m pytest tests/test_golden.py")
        want = ref.read_text(encoding="utf-8")
        if got != want:
            # Point at the first differing line — a whole .nc diff is unreadable.
            g, w = got.splitlines(), want.splitlines()
            for i, (a, b) in enumerate(zip(g, w), start=1):
                if a != b:
                    pytest.fail(
                        f"{produced.name} changed at line {i}:\n"
                        f"  golden : {b!r}\n"
                        f"  now    : {a!r}\n"
                        f"(see this file's docstring before blessing the change)")
            pytest.fail(
                f"{produced.name} changed length: golden has {len(w)} lines, "
                f"now {len(g)}")


def test_build_is_deterministic(tmp_path):
    """Two runs in one process must agree — catches set/dict iteration order
    leaking into the toolpath order, which would make the golden files flap."""
    a = _build(tmp_path / "a", "Roland SRM-20 (G-code)", "det")
    b = _build(tmp_path / "b", "Roland SRM-20 (G-code)", "det")
    assert [p.name for p in a] == [p.name for p in b]
    for pa, pb in zip(a, b):
        assert pa.read_text(encoding="utf-8") == pb.read_text(encoding="utf-8"), \
            f"{pa.name} differs between two runs of the same input"
