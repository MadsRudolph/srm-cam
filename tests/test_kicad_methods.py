"""KiCad's "Set design rules for SRM-CAM" window: the rules per fabrication method.

The plugin module is pure (no pcbnew, no wx), loaded straight off disk the way
KiCad would. The KiCad side (srm20area/rules.py, rules_dialog.py) was checked
against KiCad 10.0.7 by hand: each method applied to real boards, refilled,
DRC'd and the copper gaps measured.
"""
import importlib.util

import pytest

from gerber2rml.engine import kicadplugin


def _methods():
    path = kicadplugin.bundled_source() / "srm20area" / "methods.py"
    spec = importlib.util.spec_from_file_location("_srm20area_methods", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _methods()


def _board(clearance=0.5, track=0.5, pour=0.5, thermal=0.5, pour_min=0.5,
           floor=0.5, extra_classes=None):
    classes = {"Default": {"clearance": clearance, "track": track,
                           "via_drill": 0.8, "via_dia": 1.8}}
    classes.update(extra_classes or {})
    return {"board": {"floor": floor, "edge": 0.5, "drill": 0.8},
            "classes": classes,
            "zones": [{"name": "GND", "clearance": pour, "thermal_gap": thermal,
                       "pour_min": pour_min}],
            "zone_defaults": {"clearance": pour, "thermal_gap": thermal,
                              "pour_min": pour_min}}


def test_every_method_fills_every_field_of_the_window():
    keys = {k for k, _ in M.FIELDS}
    for m in M.METHODS:
        assert set(M.defaults(m["id"], 0.8)) == keys, m["id"]


def test_the_numbers_are_the_ones_that_were_cut():
    flat, ball, laser = (M.defaults(i) for i in ("mill_flat", "mill_ball", "laser"))
    assert (flat["track"], flat["clearance"]) == (1.0, 0.85)
    assert (ball["track"], ball["clearance"]) == (0.5, 0.5)
    # the laser clears ~0.22 mm round every edge: the pour stands 0.25 mm off
    assert laser["pour_gap"] == laser["thermal_gap"] == laser["pour_min"] == 0.25
    assert laser["track"] == 0.3


def test_every_method_drills_with_the_drill_srm_cam_has():
    for m in M.METHODS:
        assert M.defaults(m["id"], 1.0)["drill"] == 1.0
        assert M.defaults(m["id"])["drill"] == M.DEFAULT_DRILL_MM


def test_no_method_asks_for_a_gap_under_its_own_floor():
    for m in M.METHODS:
        v = M.defaults(m["id"])
        assert v["clearance"] >= v["floor"]
        assert v["pour_gap"] >= v["floor"]


def test_laser_lowers_the_pour_and_clearance_of_a_milled_board():
    ops = M.plan(_board(), M.defaults("laser"))
    got = {(t if isinstance(t, str) else t[0], k): new for t, k, _o, new in ops}
    assert got[("zone", "clearance")] == 0.25
    assert got[("zone", "thermal_gap")] == 0.25
    assert got[("zone", "pour_min")] == 0.25
    assert got[("class", "clearance")] == 0.25
    assert got[("board", "floor")] == 0.2
    assert got[("zone_defaults", "clearance")] == 0.25


def test_mill_raises_a_laser_board_back():
    ops = M.plan(_board(clearance=0.25, track=0.3, pour=0.25, thermal=0.25,
                        pour_min=0.25, floor=0.2), M.defaults("mill_ball"))
    got = {(t if isinstance(t, str) else t[0], k): new for t, k, _o, new in ops}
    assert got[("zone", "clearance")] == 0.5
    assert got[("zone", "thermal_gap")] == 0.5
    assert got[("class", "track")] == 0.5
    assert got[("board", "floor")] == 0.44


def test_a_board_already_set_needs_nothing():
    v = M.defaults("mill_ball")
    board = _board(floor=0.44)
    assert M.plan(board, v) == []


def test_a_wider_power_class_keeps_its_tracks():
    board = _board(extra_classes={"Power": {"clearance": 0.5, "track": 1.0,
                                            "via_drill": 0.8, "via_dia": 1.8}})
    ops = M.plan(board, M.defaults("laser"))
    assert not [o for o in ops if o[0] == ("class", "Power") and o[1] == "track"]
    assert [o for o in ops if o[0] == ("class", "Default") and o[1] == "track"]


def test_holes_are_only_ever_raised_to_the_drill():
    board = _board()
    board["board"]["drill"] = 1.2
    board["classes"]["Default"]["via_drill"] = 1.2
    ops = M.plan(board, M.defaults("laser", 0.8))
    assert not [o for o in ops if o[1] in ("drill", "via_drill")]
    board["board"]["drill"] = 0.3
    ops = M.plan(board, M.defaults("laser", 0.8))
    assert ("board", "drill", 0.3, 0.8) in ops


def test_every_change_reads_as_a_line():
    ops = M.plan(_board(), M.defaults("laser"))
    lines = [M.describe(o, ["GND"]) for o in ops]
    assert "Zone GND clearance to other copper 0.50 -> 0.25 mm" in lines
    assert "Net class Default clearance 0.50 -> 0.25 mm" in lines


def test_send_check_follows_the_method():
    laser_board = _board(clearance=0.25, pour=0.25, thermal=0.25, floor=0.2)
    assert M.too_tight(laser_board, M.defaults("laser")) == []
    tight = M.too_tight(laser_board, M.defaults("mill_flat"))
    assert any("Net class Default clearance" in t for t in tight)
    assert any("Zone GND thermal gap" in t for t in tight)


DRU = """(version 1)
# a comment with (rule "fake" ...) in it
(rule "ball_mill_clearance"
\t(constraint clearance (min 0.5mm)))

(rule "fine_pitch"
\t(condition "A.memberOfFootprint('U1') && B.memberOfFootprint('U1')")
\t(constraint clearance (min 0.3mm)))

(rule "ignored"
\t(constraint clearance (min 0.1mm))
\t(severity ignore))

(rule "courtyard"
\t(constraint courtyard_clearance (min 0mm)))
"""

LASER_POUR = """
(rule "laser_pour_clearance"
\t(condition "A.Type == 'Zone' || B.Type == 'Zone'")
\t(constraint clearance (min 0.25mm)))
"""


def test_reads_the_clearance_rules_and_nothing_else():
    rules = M.clearance_rules(DRU)
    assert [r[0] for r in rules] == ["ball_mill_clearance", "fine_pitch"]
    assert rules[0][1] is None and rules[0][2] == 0.5
    assert "memberOfFootprint" in rules[1][1]


def test_reads_mils():
    rules = M.clearance_rules('(rule x (constraint clearance (min 20mil)))')
    assert rules == [("x", None, 0.508)]


def test_a_rule_holding_the_pour_wider_than_the_laser_wants_is_named():
    notes = M.rule_file_notes(DRU, M.defaults("laser"))
    assert any('"ball_mill_clearance" holds the pour 0.50' in n for n in notes)


def test_a_later_pour_rule_overrides_the_earlier_one():
    assert M.rule_file_notes(DRU + LASER_POUR, M.defaults("laser")) == []


def test_a_rule_under_the_tool_is_named_for_the_mill():
    notes = M.rule_file_notes(DRU + LASER_POUR, M.defaults("mill_flat"))
    names = " ".join(notes)
    assert '"fine_pitch" allows 0.30' in names
    assert '"laser_pour_clearance" allows 0.25' in names
    assert '"ignored"' not in names


def test_the_method_is_remembered_per_board(tmp_path):
    a, b = tmp_path / "a.kicad_pcb", tmp_path / "b.kicad_pcb"
    assert M.read_method(str(a)) == (None, None)
    M.write_method(str(a), "laser", M.defaults("laser"))
    M.write_method(str(b), "mill_ball", M.defaults("mill_ball"))
    assert M.read_method(str(a))[0] == "laser"
    assert M.read_method(str(b))[0] == "mill_ball"
    assert (tmp_path / "srm-cam" / "method.json").is_file()


def test_a_broken_method_file_is_not_trusted(tmp_path):
    (tmp_path / "srm-cam").mkdir()
    (tmp_path / "srm-cam" / "method.json").write_text("{ not json")
    assert M.read_method(str(tmp_path / "a.kicad_pcb")) == (None, None)
    M.write_method(str(tmp_path / "a.kicad_pcb"), "laser", {})
    assert M.read_method(str(tmp_path / "a.kicad_pcb"))[0] == "laser"


def test_an_unknown_method_is_refused():
    with pytest.raises(KeyError):
        M.defaults("waterjet")


# ------------------------------------------------ a guess, for a board unset
def _kicad_new_board():
    """KiCad's own numbers on a board nobody has set rules for."""
    return _board(clearance=0.2, track=0.2, pour=0.5, thermal=0.5, floor=0.0)


def test_a_laser_board_is_guessed_as_laser_whatever_bit_is_in_the_mill():
    laser = M.defaults("laser")
    board = _board(clearance=laser["clearance"], pour=laser["pour_gap"],
                   floor=laser["floor"])
    assert M.guess_from_rules(board, 0.8) == "laser"
    assert M.guess_from_rules(board, 0.4) == "laser"
    # any one gap under the ball mill's channel is enough: a pour...
    assert M.guess_from_rules(_board(clearance=0.85, floor=0.8, pour=0.3),
                              0.8) == "laser"
    # ...or the board's minimum
    assert M.guess_from_rules(_board(clearance=0.85, floor=0.3, pour=0.85),
                              0.8) == "laser"


def test_a_ball_mill_board_is_guessed_as_the_ball_mill():
    ball = M.defaults("mill_ball")
    board = _board(clearance=ball["clearance"], pour=ball["pour_gap"],
                   floor=ball["floor"])                 # 0.44: not under it
    assert M.guess_from_rules(board, 0.8) == "mill_ball"


def test_a_flat_board_falls_back_to_the_bit_in_the_mill():
    flat = M.defaults("mill_flat")
    board = _board(clearance=flat["clearance"], pour=flat["pour_gap"],
                   floor=flat["floor"])
    assert M.guess_from_rules(board, 0.8) == "mill_flat"
    assert M.guess_from_rules(board, 0.44) == "mill_ball"


def test_kicad_defaults_say_nothing_about_the_method():
    # 0.2 mm clearance and a 0.5 mm pour are KiCad's, not a laser's or a
    # ball mill's: the bit SRM-CAM has selected decides, as before.
    assert M.guess_from_rules(_kicad_new_board(), 0.8) == "mill_flat"
    assert M.guess_from_rules(_kicad_new_board(), 0.44) == "mill_ball"
    assert M.guess_from_rules({}, 0.8) == "mill_flat"
    assert M.guess_from_cutter(None) == "mill_flat"


def test_a_guessed_laser_board_passes_the_laser_check_and_fails_the_mill():
    laser = M.defaults("laser")
    board = _board(clearance=laser["clearance"], pour=laser["pour_gap"],
                   thermal=laser["thermal_gap"], floor=laser["floor"])
    guess = M.guess_from_rules(board, 0.8)
    assert M.too_tight(board, M.defaults(guess, 0.8)) == []
    assert M.too_tight(board, M.defaults("mill_flat", 0.8))
