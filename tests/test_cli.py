from pathlib import Path
from gerber2rml.cli import build_jobs

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_build_jobs_writes_rml(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="mosfet_test",
                         machine="Roland SRM-20")   # RML backend (default is now NC)
    names = {p.name for p in written}
    assert "mosfet_test_traces.rml" in names
    assert "mosfet_test_cutout.rml" in names
    # drill is split into one file per diameter (default mode)
    assert any(n.startswith("mosfet_test_drill_") and n.endswith("mm.rml") for n in names)
    for p in written:
        if p.suffix == ".rml":
            text = p.read_text()
            assert text.startswith("^IN;!MC1;")   # spindle on
            assert text.rstrip().endswith("!MC0;^IN;")


def test_build_jobs_writes_runplan(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="m")
    names = {p.name for p in written}
    assert "m_runplan.txt" in names


def test_build_jobs_single_bit_makes_one_drill_file(tmp_path):
    from gerber2rml.config import DrillJob
    written = build_jobs(FIXT, tmp_path, name="m", machine="Roland SRM-20",
                         drill=DrillJob(single_bit=True, bit_diameter=0.8))
    drills = sorted(p.name for p in written if "_drill" in p.name and p.suffix == ".rml")
    assert drills == ["m_drill.rml"]            # one combined single-bit file
