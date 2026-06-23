"""Test presets: built-in, repo example, and user presets."""
from gerber2rml.app.presets import load_presets, apply_preset, save_user_preset, BUILTIN_PRESETS
from gerber2rml.app.state import ProjectState


def test_only_one_builtin_preset():
    # We ship a single profile: the SRM-20 0.8 mm flat endmill.
    assert len(BUILTIN_PRESETS) == 1
    name = next(iter(BUILTIN_PRESETS))
    assert name.startswith("SRM-20")


def test_srm20_preset_depths_and_feeds():
    name = next(iter(BUILTIN_PRESETS))         # first = the default in the GUI
    p = BUILTIN_PRESETS[name]
    assert p["trace"]["bit_diameter"] == 0.8   # one 0.8 mm bit for everything
    assert p["trace"]["xy_feed"] == 4.0
    assert p["drill"]["total_depth"] == 1.7    # 1.6 mm board + 0.1 mm through
    assert p["cutout"]["total_depth"] == 1.7


def test_apply_preset_sets_jobs():
    st = ProjectState()
    name = next(iter(BUILTIN_PRESETS))
    apply_preset(st, BUILTIN_PRESETS[name])
    assert st.trace.bit_diameter == 0.8
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
