"""Per-tool cut-distance ledger."""
from gerber2rml.engine.toolwear import (cut_distance_mm, record, total_m,
                                        wear_note)
from gerber2rml.toolpath import Move


def test_cut_distance_skips_rapids():
    tp = [[Move(0, 0, 2, rapid=True), Move(0, 0, -0.15, rapid=False),
           Move(30, 40, -0.15, rapid=False),      # 50 mm cut
           Move(30, 40, 2, rapid=True), Move(0, 0, 2, rapid=True)]]
    assert abs(cut_distance_mm(tp) - 50.0) < 1e-9


def test_record_accumulates_across_calls(tmp_path):
    p = tmp_path / "wear.json"
    record("flat 0.80mm", 12000.0, path=p)
    record("flat 0.80mm", 8000.0, path=p)
    record("vbit 0.20mm", 500.0, path=p)
    assert abs(total_m("flat 0.80mm", path=p) - 20.0) < 1e-9
    assert abs(total_m("vbit 0.20mm", path=p) - 0.5) < 1e-9


def test_wear_note_warns_past_threshold(tmp_path):
    p = tmp_path / "wear.json"
    assert wear_note("flat 0.80mm", path=p) == ""       # no history: silent
    record("flat 0.80mm", 10_000.0, path=p)
    n = wear_note("flat 0.80mm", path=p)
    assert "10.0 m" in n and "WORN" not in n
    record("flat 0.80mm", 20_000.0, path=p)
    n = wear_note("flat 0.80mm", path=p)
    assert "30.0 m" in n and "WORN" in n
