"""Test presets: built-in, repo example, and user presets."""
from gerber2rml.app.presets import load_presets, apply_preset, save_user_preset, BUILTIN_PRESETS
from gerber2rml.app.state import ProjectState


def test_builtin_present():
    presets = load_presets()
    assert any("1/64" in name for name in presets)


def test_apply_preset_sets_jobs():
    st = ProjectState()
    name = next(iter(BUILTIN_PRESETS))
    apply_preset(st, BUILTIN_PRESETS[name])
    assert st.trace.bit_diameter == 0.4
    assert st.cutout.tabs == 4


def test_save_and_load_user_preset(tmp_path, monkeypatch):
    monkeypatch.setattr("gerber2rml.app.presets._user_path",
                        lambda: tmp_path / "presets.json")
    st = ProjectState()
    st.trace.bit_diameter = 0.6
    save_user_preset("mine", st)
    presets = load_presets()
    assert "mine" in presets
    assert presets["mine"]["trace"]["bit_diameter"] == 0.6
