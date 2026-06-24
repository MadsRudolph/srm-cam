from pathlib import Path
from gerber2rml.app.state import ProjectState

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"

def test_load_then_toolpaths_per_op():
    st = ProjectState()
    st.load(FIXT)
    assert st.board is not None
    assert len(st.toolpaths("traces")) > 0
    assert len(st.toolpaths("drill")) > 0
    assert len(st.toolpaths("cutout")) > 0

def test_toolpaths_requires_load():
    import pytest
    st = ProjectState()
    with pytest.raises(RuntimeError):
        st.toolpaths("traces")

def test_export_writes_files(tmp_path):
    st = ProjectState(name="demo")            # default machine is now G-code
    st.load(FIXT)
    written = st.export(tmp_path)
    assert any(p.name == "demo_traces.nc" for p in written)


def test_set_placement_offsets_toolpaths():
    st = ProjectState()
    st.load(FIXT)
    base = st.toolpaths("traces")
    bx = min(m.x for tp in base for m in tp)
    by = min(m.y for tp in base for m in tp)
    st.set_placement(10.0, 20.0)              # move the job on the bed
    moved = st.toolpaths("traces")
    mx = min(m.x for tp in moved for m in tp)
    my = min(m.y for tp in moved for m in tp)
    assert abs((mx - bx) - 10.0) < 1e-6 and abs((my - by) - 20.0) < 1e-6
    st.set_placement(0.0, 0.0)                # back to origin restores coordinates
    back = st.toolpaths("traces")
    assert abs(min(m.x for tp in back for m in tp) - bx) < 1e-6
