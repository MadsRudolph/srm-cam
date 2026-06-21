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
    st = ProjectState(name="demo")
    st.load(FIXT)
    written = st.export(tmp_path)
    assert any(p.name == "demo_traces.rml" for p in written)
