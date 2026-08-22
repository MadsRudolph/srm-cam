"""The palette has one home, and these tests keep it that way.

The GUI used to carry 97 distinct colour literals across 236 uses. The point of
gerber2rml/gui/theme.py is not tidiness for its own sake: it is that a value
used in two places for two reasons is invisible until it has a name, and that a
colour nobody can find is a colour nobody can change.
"""
import re
from pathlib import Path

import pytest

from gerber2rml.gui import theme

GUI = Path(__file__).parent.parent / "gerber2rml" / "gui"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _tokens():
    return {k: v for k, v in vars(theme).items()
            if k.isupper() and isinstance(v, str)}


def test_no_colour_literals_outside_theme():
    offenders = []
    for f in sorted(GUI.rglob("*.py")):
        if f.name == "theme.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            for m in HEX.findall(line):
                offenders.append(f"{f.name}:{i}  {m}  {line.strip()[:70]}")
    assert not offenders, (
        "raw colour literals found - add a role name to theme.py instead:\n  "
        + "\n  ".join(offenders[:20]))


def test_every_token_is_a_real_colour():
    bad = {k: v for k, v in _tokens().items()
           if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", v)}
    assert not bad, bad


def test_stylesheet_is_fully_substituted():
    """A typo'd $NAME would sail through as literal text and Qt would discard
    the whole rule silently."""
    from gerber2rml.gui import app
    assert "$" not in app._STYLESHEET


def test_stylesheet_only_uses_colours_from_the_palette():
    from gerber2rml.gui import app
    known = {v.lower() for v in _tokens().values()}
    used = {m.lower() for m in HEX.findall(app._STYLESHEET)}
    assert used <= known, sorted(used - known)


def test_the_canvas_matches_the_window_it_sits_in():
    """The plot background used to be #1e1e1e - a fifth grey, visibly warmer
    than the chrome around it - while photodlg used the chrome colour for the
    same surface. The app's two plot surfaces disagreed with each other."""
    assert theme.CANVAS_BG == theme.BG


@pytest.mark.parametrize("name", ["ACCENT", "DANGER", "WARN", "OK", "CUT",
                                  "RAPID", "HOLE", "PIN", "BG", "TEXT"])
def test_the_load_bearing_roles_exist(name):
    """Renaming one of these is a real decision, not a refactor: they are what
    the rest of the app asks for by name."""
    assert hasattr(theme, name)


def test_link_live_is_not_the_same_token_as_ok():
    """"the wire is live" and "this step is done" are different questions, and
    were being answered with the same green."""
    assert theme.LINK_LIVE != theme.OK


def test_rework_series_is_long_enough_to_be_told_apart():
    assert len(theme.REWORK_SERIES) >= 6
    assert len(set(theme.REWORK_SERIES)) == len(theme.REWORK_SERIES)
