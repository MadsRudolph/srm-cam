from pathlib import Path
from gerber2rml.cli import build_jobs

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_build_jobs_writes_three_rml(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="mosfet_test")
    names = {p.name for p in written}
    assert "mosfet_test_traces.rml" in names
    assert "mosfet_test_drill.rml" in names
    assert "mosfet_test_cutout.rml" in names
    for p in written:
        if p.suffix == ".rml":
            text = p.read_text()
            assert text.startswith("^IN;!MC1;")   # spindle on
            assert text.rstrip().endswith("!MC0;^IN;")


def test_build_jobs_writes_runplan(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="m")
    names = {p.name for p in written}
    assert "m_runplan.txt" in names
    assert len(written) == 4                   # 3 rml + 1 runplan
