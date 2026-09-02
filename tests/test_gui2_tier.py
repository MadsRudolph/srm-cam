"""Two tiers, one code path.

The property that matters is the one the brief calls non-negotiable: what a
student produces in the simpler tier is byte for byte what a teacher produces
in the full one. If those two ever diverge there are two programs, and the one
students use is the one nobody tests.

These deliberately drive the tier through ``SRM_CAM_MODE`` rather than through
the stored preference. Two reasons: it is what a lab pinning its seats actually
does, and it keeps the test run out of the developer's real QSettings.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton

from gerber2rml.gui2 import tier
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


def _window(monkeypatch, mode):
    monkeypatch.setenv("SRM_CAM_MODE", mode)
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    return w


def _visible_controls(w):
    """Everything clickable that the tier has not put away.

    ``isHidden()`` is True only for something explicitly hidden, which is
    exactly what the tier does — so this reports the tier's decisions and not
    the accident of which stack page happens to be on top.
    """
    out = {b.text() for b in w.findChildren(QAbstractButton)
           if not b.isHidden() and b.text()}
    out |= {a.text() for a in w.findChildren(QAction)
            if a.isVisible() and a.text()}
    return out


def test_the_environment_pin_is_honoured(monkeypatch):
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    assert tier.current_tier() == tier.ESSENTIAL
    monkeypatch.setenv("SRM_CAM_MODE", "professional")
    assert tier.current_tier() == tier.FULL
    monkeypatch.setenv("SRM_CAM_MODE", "full")
    assert tier.current_tier() == tier.FULL
    assert tier.set_tier(tier.ESSENTIAL) is False       # pinned: menu is inert


def test_the_first_interfaces_vocabulary_still_works(monkeypatch):
    """A lab that already pinned its seats with the original interface's words
    should not have to do it twice."""
    for word, expect in (("novice", tier.ESSENTIAL), ("pro", tier.FULL)):
        monkeypatch.setenv("SRM_CAM_MODE", word)
        assert tier.current_tier() == expect


def test_essential_is_the_default(monkeypatch):
    monkeypatch.delenv("SRM_CAM_MODE", raising=False)
    monkeypatch.setattr(tier, "_settings", lambda: _NoSettings())
    assert tier.current_tier() == tier.ESSENTIAL


class _NoSettings:
    """A QSettings stand-in, so the default-tier test never touches the real
    one on the developer's machine."""

    def value(self, _key, default=None):
        return default

    def setValue(self, _key, _value):
        pass


def test_the_two_tiers_export_identical_bytes(qt_app, monkeypatch, tmp_path):
    """The whole point. Same settings, same files, down to the byte."""
    a, b = tmp_path / "essential", tmp_path / "full"
    w1 = _window(monkeypatch, "novice")
    try:
        assert not tier.is_full()
        w1.export_to(a)
    finally:
        w1.close()
    w2 = _window(monkeypatch, "pro")
    try:
        assert tier.is_full()
        w2.export_to(b)
    finally:
        w2.close()

    names_a = sorted(p.name for p in a.iterdir())
    names_b = sorted(p.name for p in b.iterdir())
    assert names_a == names_b, (names_a, names_b)
    for name in names_a:
        # The run plan names its own folder; everything else must match byte
        # for byte.
        if name.endswith("_runplan.txt"):
            continue
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_the_plan_is_the_same_in_both_tiers(qt_app, monkeypatch):
    w1 = _window(monkeypatch, "novice")
    try:
        essential = [(s.key, s.ordinal, s.file) for s in w1.plan]
    finally:
        w1.close()
    w2 = _window(monkeypatch, "pro")
    try:
        full = [(s.key, s.ordinal, s.file) for s in w2.plan]
    finally:
        w2.close()
    assert essential == full


def test_essential_is_a_strict_subset(qt_app, monkeypatch):
    """Not a second interface: everything in the simpler tier is also in the
    fuller one, so there is nothing that can drift between them."""
    w1 = _window(monkeypatch, "novice")
    try:
        essential = _visible_controls(w1)
    finally:
        w1.close()
    w2 = _window(monkeypatch, "pro")
    try:
        full = _visible_controls(w2)
    finally:
        w2.close()
    assert essential <= full, sorted(essential - full)
    assert full - essential, "the full tier is supposed to add something"


def test_essential_keeps_bed_levelling(qt_app, monkeypatch):
    """The thing the first interface had to take out of its beginner mode.

    It can stay here because the stop control is not in a hideable panel — see
    ``gui2/machine.py``. Levelling is what makes cut depth follow the real
    surface, and that is what decides whether isolation actually separates two
    tracks, so it is the single most useful thing the Arduino buys a beginner.
    """
    w = _window(monkeypatch, "novice")
    try:
        assert w.plan.by_key("level") is not None
        w.select_step("level")
        assert w.inspector.stack.currentWidget() is w.level_page
        assert w.bar.stop_btn.isEnabled()
        assert not w.bar.stop_btn.isHidden()
    finally:
        w.close()


def test_essential_keeps_the_dry_run_and_the_checks(qt_app, monkeypatch):
    w = _window(monkeypatch, "novice")
    try:
        assert w.plan.by_key("airpass").ordinal == 0
        assert w.plan.by_key("checks") is not None
        assert w._checks
    finally:
        w.close()


def test_essential_puts_away_the_experimental_stream(qt_app, monkeypatch):
    """Streaming is gated on uncalibrated speed units and is not the way this
    lab runs jobs, so it is not on the beginner's happy path."""
    w = _window(monkeypatch, "novice")
    try:
        assert not w.stream_act.isVisible()
    finally:
        w.close()
    w = _window(monkeypatch, "pro")
    try:
        assert w.stream_act.isVisible()
        assert "experimental" in w.stream_act.text().lower()
    finally:
        w.close()


def test_the_menu_says_exactly_what_the_other_tier_adds():
    """Nobody should have to guess whether the control they remember is gone or
    merely put away."""
    assert len(tier.ADDED_BY_FULL) >= 5
    assert all(len(t) > 30 for t in tier.ADDED_BY_FULL)
    assert len(tier.KEPT_IN_ESSENTIAL) >= 4
    for name, why in tier.KEPT_IN_ESSENTIAL:
        assert name and len(why) > 40, name
