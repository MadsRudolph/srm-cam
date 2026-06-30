from pathlib import Path
from gerber2rml.cli import build_jobs

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def test_build_jobs_writes_rml(tmp_path):
    written = build_jobs(FIXT, tmp_path, name="mosfet_test",
                         machine="Roland SRM-20")   # RML backend (default is now NC)
    names = {p.name for p in written}
    assert "mosfet_test_traces.rml" in names
    assert "mosfet_test_cutout.rml" in names
    # default is single-bit: one combined drill file (not split per diameter)
    assert "mosfet_test_drill.rml" in names
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


def test_lead_in_on_by_default_ramps_traces(tmp_path):
    from gerber2rml.engine.leadin import RAMP_CLEARANCE
    on = build_jobs(FIXT, tmp_path / "on", name="m")          # default lead_in=True
    off = build_jobs(FIXT, tmp_path / "off", name="m", lead_in=False)
    tag = f"Z{RAMP_CLEARANCE:g}"                                # ramp's clearance hop
    traces_on = next(p for p in on if p.name == "m_traces.nc").read_text()
    traces_off = next(p for p in off if p.name == "m_traces.nc").read_text()
    assert tag in traces_on                                     # ramp present
    assert tag not in traces_off                                # straight plunge


def test_cli_multi_bit_flag_splits_per_diameter(tmp_path):
    from gerber2rml.cli import main
    main([str(FIXT), "-o", str(tmp_path), "-n", "m", "-m", "Roland SRM-20",
          "--multi-bit"])
    drills = sorted(p.name for p in tmp_path.glob("m_drill*.rml"))
    assert drills and all(n.endswith("mm.rml") for n in drills)   # split per diameter
