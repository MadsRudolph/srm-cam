"""The extra depth for a board held at points.

Charging the whole arch of the probe map cut a 0.15 mm trace 0.5 mm deep on
a real board. The warp already follows the arch; what it cannot cover is the
give under the cutter, which is a fraction of it - and the operator who has
cut the board knows the number better than any estimate.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path

import pytest

from gerber2rml.gui2.window import (FLEX_CAP_MM, FLEX_FRACTION, FOIL_MM,
                                    MainWindow)

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def loaded(qt_app):
    w = MainWindow()
    w.resize(1200, 800)
    w.load_folder(str(FIXT))
    w.action_hold("points")
    yield w
    w.close()


def _domed(bump):
    """A sloped sheet with the middle point ``bump`` mm proud of the plane."""
    return [[f"{x:.3f}", f"{y:.3f}",
             f"{0.008 * x + (bump if (x, y) == (55.0, 55.0) else 0.0):.4f}"]
            for y in (10.0, 55.0, 100.0) for x in (10.0, 55.0, 100.0)]


def _apply(win, rows):
    win.level_page._load_table({"rows": rows, "apply": True, "show": False})


def test_a_quarter_of_the_arch_is_charged(loaded):
    _apply(loaded, _domed(0.25))
    assert loaded._flex_margin() == pytest.approx(
        0.25 * FLEX_FRACTION + FOIL_MM, abs=1e-3)
    assert loaded.cutting_trace().cut_depth == pytest.approx(
        loaded.state.trace.cut_depth + loaded._flex_margin())


def test_the_charge_is_capped(loaded):
    _apply(loaded, _domed(1.0))
    assert loaded._flex_margin() == pytest.approx(FLEX_CAP_MM + FOIL_MM)
    assert loaded.flex_report()["capped"]
    assert "Capped" in loaded.inspector.setup.hold_note.text()


def test_the_operator_can_set_it_including_to_nothing(loaded):
    _apply(loaded, _domed(0.25))
    loaded.action_flex(False, 0.02)
    assert loaded._flex_margin() == pytest.approx(0.02)
    loaded.action_flex(False, 0.0)
    assert loaded._flex_margin() == 0.0
    assert loaded.cutting_trace().cut_depth == loaded.state.trace.cut_depth
    assert loaded.cutting_cutout().total_depth == \
        loaded.state.cutout.total_depth
    loaded.action_flex(True, 0.0)
    assert loaded._flex_margin() == pytest.approx(
        0.25 * FLEX_FRACTION + FOIL_MM, abs=1e-3)


def test_the_page_shows_the_number_in_use_and_frees_it_when_unticked(loaded):
    _apply(loaded, _domed(0.25))
    page = loaded.inspector.setup
    page.sync()
    assert page.flex_auto.isChecked() and not page.flex_mm.isEnabled()
    assert page.flex_mm.value() == pytest.approx(loaded._flex_margin(), abs=1e-3)
    page.flex_auto.setChecked(False)            # the handler runs
    assert page.flex_mm.isEnabled()
    assert not loaded._flex_auto
    assert loaded._flex_margin() == pytest.approx(page.flex_mm.value(), abs=1e-3)


def test_bonded_hides_the_controls(loaded):
    loaded.action_hold("bonded")
    page = loaded.inspector.setup
    page.sync()
    assert not page.flex_field.isVisibleTo(page)
    assert loaded._flex_margin() == 0.0


def test_a_typed_depth_survives_the_setup_file(loaded, tmp_path, monkeypatch):
    loaded.action_flex(False, 0.04)
    path = tmp_path / "f.srmcam"
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    loaded.action_save_setup()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["flex_auto"] is False and data["flex_mm"] == pytest.approx(0.04)
    fresh = MainWindow()
    try:
        monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                            lambda *a, **k: (str(path), ""))
        fresh.action_load_setup()
        assert not fresh._flex_auto
        assert fresh._flex_margin() == pytest.approx(0.04)
    finally:
        fresh.close()
