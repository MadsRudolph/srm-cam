"""Cutout engine tests (TDD — Task 7)."""
from shapely.geometry import box
from gerber2rml.config import CutoutJob
from gerber2rml.engine.cutout import cut_outline


def test_cutout_passes_reach_total_depth():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(cut_depth=0.6, total_depth=1.8, tabs=0)
    paths = cut_outline(outline, job)
    deepest = min(m.z for tp in paths for m in tp if not m.rapid)
    assert deepest <= -1.8


def test_outline_is_offset_outward():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(bit_diameter=0.8, tabs=0, cut_depth=0.6, total_depth=0.6)
    paths = cut_outline(outline, job)
    xs = [m.x for tp in paths for m in tp if not m.rapid]
    assert min(xs) < 0          # cut path rides outside the board edge


def test_tabs_create_gaps():
    outline = box(0, 0, 20, 20)
    job = CutoutJob(tabs=4, tab_width=1.5, cut_depth=0.6, total_depth=0.6)
    paths_with = cut_outline(outline, job)
    paths_without = cut_outline(outline, CutoutJob(tabs=0, cut_depth=0.6, total_depth=0.6))
    n_with = sum(len(tp) for tp in paths_with)
    n_without = sum(len(tp) for tp in paths_without)
    assert n_with > n_without   # tabs split the ring into more, shorter paths
