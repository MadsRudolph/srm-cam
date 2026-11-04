"""Test presets: built-in, repo example, and user presets."""
from gerber2rml.app.presets import load_presets, apply_preset, save_user_preset, BUILTIN_PRESETS
from gerber2rml.app.state import ProjectState


def test_builtin_presets_are_the_flat_and_ball_mill_profiles():
    # We ship two profiles: the 0.8 mm flat endmill (default, first) and the
    # 0.8 mm ball mill for fine SMD work.
    assert len(BUILTIN_PRESETS) == 2
    names = list(BUILTIN_PRESETS)
    assert all(n.startswith("SRM-20") for n in names)
    assert names[0].startswith("SRM-20 0.8 mm flat")     # default stays first
    assert names[1].startswith("SRM-20 0.8 mm ball mill")


def test_ball_mill_preset_holds_the_measured_settings():
    ball = BUILTIN_PRESETS[list(BUILTIN_PRESETS)[1]]
    assert ball["trace"]["bit_diameter"] == 0.44    # measured channel, not the shank
    assert ball["trace"]["cut_depth"] == 0.08
    assert ball["trace"]["cut_pinches"] is True
    assert ball["drill"]["bit_diameter"] == 0.8     # real holes and outline
    assert ball["drill"]["total_depth"] == 1.9
    assert ball["cutout"]["total_depth"] == 1.9
    assert ball["cutout"]["tabs"] == 4


def test_ball_mill_preset_applies_every_field():
    st = ProjectState()
    apply_preset(st, BUILTIN_PRESETS[list(BUILTIN_PRESETS)[1]])
    assert st.trace.tool_type == "flat"
    assert st.trace.effective_diameter() == 0.44
    assert st.trace.cut_pinches is True
    assert st.drill.bit_diameter == 0.8
    assert st.cutout.bit_diameter == 0.8


def test_srm20_preset_depths_and_feeds():
    name = next(iter(BUILTIN_PRESETS))         # first = the default in the GUI
    p = BUILTIN_PRESETS[name]
    assert p["trace"]["bit_diameter"] == 0.8   # one 0.8 mm bit for everything
    assert p["trace"]["xy_feed"] == 4.0
    assert p["drill"]["total_depth"] == 1.9    # 1.6 mm board + 0.3 mm through
    assert p["cutout"]["total_depth"] == 1.9


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
