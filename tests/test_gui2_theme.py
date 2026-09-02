"""The second interface's palette has one home, and these tests keep it there.

Same discipline as ``tests/test_theme.py`` applies to ``gerber2rml/gui/``, for
the same reason: a colour used in two places for two reasons is invisible until
it has a name, and a colour nobody can find is a colour nobody can change.

Two rules here that the first interface's tests do not have, because this
interface makes two extra promises:

* the type scale has a real range (it is the thing §4 of the brief calls out
  first), so a change that flattens it back to "everything is 13 px" fails;
* the interface chrome carries no hue, so that when something goes red you
  look at it.
"""
import re
from pathlib import Path

import pytest

from gerber2rml.gui2 import theme

GUI2 = Path(__file__).parent.parent / "gerber2rml" / "gui2"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _tokens():
    return {k: v for k, v in vars(theme).items()
            if k.isupper() and isinstance(v, str) and v.startswith("#")}


def test_no_colour_literals_outside_theme():
    offenders = []
    for f in sorted(GUI2.rglob("*.py")):
        if f.name == "theme.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            for m in HEX.findall(line):
                offenders.append(f"{f.name}:{i}  {m}  {line.strip()[:70]}")
    assert not offenders, (
        "raw colour literals found - add a role name to gui2/theme.py "
        "instead:\n  " + "\n  ".join(offenders[:20]))


def test_every_token_is_a_real_colour():
    bad = {k: v for k, v in _tokens().items()
           if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", v)}
    assert not bad, bad


def test_stylesheet_is_fully_substituted():
    """A typo'd $NAME sails through as literal text and Qt discards the whole
    rule silently."""
    from gerber2rml.gui2 import style
    assert "$" not in style.STYLESHEET


def test_stylesheet_only_uses_colours_from_the_palette():
    from gerber2rml.gui2 import style
    known = {v.lower() for v in _tokens().values()}
    used = {m.lower() for m in HEX.findall(style.STYLESHEET)}
    assert used <= known, sorted(used - known)


@pytest.mark.parametrize("name", ["INK", "BASE", "PANEL", "TEXT", "PRIMARY",
                                  "DANGER", "CAUTION", "VERIFIED", "LIVE",
                                  "COPPER", "PATH", "HOLE", "FIXTURE"])
def test_the_load_bearing_roles_exist(name):
    """Renaming one of these is a decision, not a refactor: they are what the
    rest of the interface asks for by name."""
    assert hasattr(theme, name)


def test_live_is_a_different_hue_from_verified():
    """"the wire is live" and "this check passed" are different questions.

    The first interface answered them with two greens. Two greens still have to
    be told apart at a glance, across a workshop, by someone holding a bit — so
    here they are different hues, and this asserts it rather than trusting it.
    """
    from PySide6.QtGui import QColor
    live, ok = QColor(theme.LIVE), QColor(theme.VERIFIED)
    assert abs(live.hue() - ok.hue()) > 60, (live.hue(), ok.hue())


def test_the_type_scale_has_a_real_range():
    """The critique of the first interface starts here: its whole UI lives
    between 11 px and 14 px, so nothing on it can read as a heading."""
    sizes = [v for k, v in vars(theme).items()
             if k.startswith("SIZE_") and isinstance(v, (int, float))]
    assert len(sizes) >= 6
    assert max(sizes) / min(sizes) >= 3.0, sorted(sizes)


def _chroma(hexcolour):
    """How far from grey a colour is, as a fraction of the full range.

    Deliberately NOT HSV saturation, which is a ratio against the value and so
    reports a near-black cool grey like ``#101318`` as 33% "saturated" — a
    number that says nothing about whether a person would call it a colour.
    Max-minus-min over 255 is what the eye is doing here.
    """
    from PySide6.QtGui import QColor
    c = QColor(hexcolour)
    ch = (c.red(), c.green(), c.blue())
    return (max(ch) - min(ch)) / 255.0


def test_the_chrome_is_neutral():
    """Panels, text, rules and the primary action carry no hue, so that hue
    means something everywhere else."""
    chrome = ["INK", "BASE", "PANEL", "PANEL_HI", "RAISED", "RAISED_HI",
              "SUNK", "RULE", "RULE_HI", "RULE_STRONG", "TEXT", "TEXT_2",
              "TEXT_3", "TEXT_4", "PRIMARY", "PRIMARY_HI", "PRIMARY_LO"]
    loud = {n: round(_chroma(getattr(theme, n)), 3) for n in chrome
            if _chroma(getattr(theme, n)) > 0.10}
    assert not loud, loud


def test_the_meaningful_colours_are_actually_coloured():
    """The other half of the same promise: a status token that is nearly grey
    would not be doing its job either."""
    meaning = ["COPPER", "DANGER", "CAUTION", "VERIFIED", "LIVE", "HOLE",
               "PROBE", "FIXTURE"]
    grey = {n: round(_chroma(getattr(theme, n)), 3) for n in meaning
            if _chroma(getattr(theme, n)) < 0.25}
    assert not grey, grey


def test_the_status_colours_are_told_apart_by_hue():
    from PySide6.QtGui import QColor
    hues = [QColor(getattr(theme, n)).hue()
            for n in ("DANGER", "CAUTION", "VERIFIED", "LIVE")]
    for i, a in enumerate(hues):
        for b in hues[i + 1:]:
            assert abs(a - b) > 25, hues


def test_font_roles_resolve_and_differ_in_size(qt_app):
    """Every role has to produce a font, and the scale has to survive the trip
    through :func:`theme.font` rather than only existing as constants."""
    sizes = {r: theme.font(r).pointSizeF()
             for r in ("hero", "title", "head", "sub", "body", "small",
                       "label", "micro")}
    assert len(set(sizes.values())) >= 6, sizes
    assert sizes["hero"] > sizes["title"] > sizes["head"] > sizes["body"]


def test_mono_is_reserved_for_machine_facts(qt_app):
    """The mono face carries a meaning — 'the machine said this' — so it has to
    actually be a different family from the prose face."""
    assert theme.font("body", mono=True).families() != \
        theme.font("body").families()
