from shapely.geometry import Point
from gerber2rml.config import TraceJob
from gerber2rml.engine.traces import isolate
from gerber2rml.toolpath import Move


def test_one_pad_makes_one_ring_per_offset():
    copper = Point(0, 0).buffer(1.0)        # 1 mm radius pad
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    assert len(paths) == 2                   # two offset passes
    for tp in paths:
        assert all(isinstance(m, Move) for m in tp)
        assert tp[0].rapid is True           # starts with a rapid approach
        assert any(m.z < 0 for m in tp)      # cuts below zero
        assert tp[-1].rapid is True          # ends lifted


def test_ring_radius_grows_by_stepover():
    copper = Point(0, 0).buffer(1.0)
    job = TraceJob(bit_diameter=0.4, offsets=2, stepover=0.5)
    paths = isolate(copper, job)
    r0 = max(abs(m.x) for m in paths[0] if not m.rapid)
    r1 = max(abs(m.x) for m in paths[1] if not m.rapid)
    assert r1 > r0                           # second pass is further out


def test_empty_copper_returns_empty():
    from shapely.geometry import Polygon
    assert isolate(Polygon(), TraceJob()) == []


def test_two_separate_pads_each_get_isolated():
    from shapely.geometry import MultiPolygon
    pad_a = Point(0, 0).buffer(1.0)
    pad_b = Point(10, 0).buffer(1.0)          # far apart -> stay separate after buffer
    copper = MultiPolygon([pad_a, pad_b])
    job = TraceJob(bit_diameter=0.4, offsets=1, stepover=0.5)
    paths = isolate(copper, job)
    assert len(paths) == 2                     # one isolation ring per pad
