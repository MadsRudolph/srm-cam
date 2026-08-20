"""The bed fixture: three dowel pins the machine drills for itself.

The point of the whole thing is that a datum the machine cut is, by
definition, already in machine coordinates — so nobody has to measure where it
is, or find the corner of a sheared piece of copper by eye.
"""
import pytest

from gerber2rml.engine import bedfixture


STOCK = (100.0, 80.0)     # a typical piece of copper-clad, mm


def test_three_pins_locate_the_stock_without_over_constraining_it():
    """3-2-1: two pins along one edge fix rotation and Y, one on the
    perpendicular edge fixes X. A fourth would fight the other three."""
    holes = bedfixture.pin_holes(*STOCK)

    assert len(holes) == 3


def test_the_pins_sit_outside_the_stock_so_it_can_butt_against_them():
    """A pin under the stock holds it up; a pin beside it locates it."""
    w, h = STOCK
    for x, y, _d in bedfixture.pin_holes(w, h):
        assert x < 0 or y < 0, f"pin at ({x}, {y}) is under the stock"


def test_two_pins_lie_along_the_bottom_edge_and_one_along_the_left():
    holes = bedfixture.pin_holes(*STOCK)
    bottom = [hole for hole in holes if hole[1] < 0]
    left = [hole for hole in holes if hole[0] < 0]

    assert len(bottom) == 2 and len(left) == 1


def test_the_bottom_pins_are_spread_wide_for_angular_accuracy():
    """Two pins 5 mm apart barely constrain rotation. Spread across the edge,
    a 0.05 mm difference in seating is a much smaller angle."""
    w, h = STOCK
    bottom = sorted(hole[0] for hole in bedfixture.pin_holes(w, h) if hole[1] < 0)

    assert bottom[1] - bottom[0] > 0.5 * w


def test_a_pin_just_touches_the_stock_edge():
    """The pin's surface must sit on the edge line, so the stock corner lands
    exactly on the work origin — not a pin radius away from it."""
    w, h = STOCK
    pin_d = 3.0
    holes = bedfixture.pin_holes(w, h, pin_diameter=pin_d)
    left = [hole for hole in holes if hole[0] < 0][0]

    assert round(left[0], 6) == -pin_d / 2


def test_the_holes_are_cut_oversize_because_milled_holes_come_out_small():
    """Interpolated holes on this machine measure ~0.2 mm under nominal — a
    hard-won number from the double-sided work, reused rather than re-learned."""
    from gerber2rml.doublesided import CLEAR_LARGE

    holes = bedfixture.pin_holes(*STOCK, pin_diameter=3.0)

    assert all(round(d, 6) == round(3.0 + CLEAR_LARGE, 6) for _x, _y, d in holes)


def test_the_layout_follows_the_stock_size():
    """A small offcut and a full sheet do not want the same pin spacing."""
    small = bedfixture.pin_holes(40.0, 30.0)
    large = bedfixture.pin_holes(160.0, 120.0)

    assert max(h[0] for h in small) < max(h[0] for h in large)


def test_it_refuses_a_stock_bigger_than_the_machine():
    """Better to say so than to drill three holes that cannot be reached."""
    from gerber2rml.backends import SRM20_BED

    with pytest.raises(ValueError, match="(?i)larger than|does not fit"):
        bedfixture.pin_holes(SRM20_BED[0] + 10, 50.0)


# --- the program that cuts it ---------------------------------------------

def test_the_program_drills_every_pin_hole_below_the_stock_surface():
    """The pins take side load, so the holes go well into the sacrificial bed
    rather than just scratching it."""
    paths = bedfixture.fixture_toolpaths(*STOCK, bed_depth=5.0)

    deepest = min(m.z for tp in paths for m in tp)
    assert deepest <= -5.0


def test_the_program_is_a_normal_cutting_job_with_the_spindle_on():
    """Unlike the dry run, this one really does cut."""
    from gerber2rml.backends import gcode

    text = gcode.render(bedfixture.fixture_toolpaths(*STOCK), xy_feed=4.0,
                        plunge_feed=1.0)

    assert "M3" in text.split()


# --- exporting it from the app --------------------------------------------

def _window(monkeypatch, mode="pro"):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import matplotlib
    matplotlib.use("Agg")
    from PySide6.QtWidgets import QApplication
    from gerber2rml.gui.app import MainWindow
    monkeypatch.setenv("SRM_CAM_MODE", mode)
    QApplication.instance() or QApplication([])
    return MainWindow()


def test_export_writes_the_program_and_the_procedure(tmp_path, monkeypatch):
    """The .nc on its own is useless — whoever runs it needs to know it wants
    a sacrificial bed, an origin 10 mm in, and three pins afterwards."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    w = _window(monkeypatch)
    w.stock_w_spin.setValue(100.0)
    w.stock_h_spin.setValue(80.0)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    w._on_export_bed_fixture()

    written = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith("_bedfixture.nc") for n in written), written
    assert any(n.endswith("_bedfixture.txt") for n in written), written


def test_the_procedure_names_the_pin_positions(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    w = _window(monkeypatch)
    w.stock_w_spin.setValue(100.0)
    w.stock_h_spin.setValue(80.0)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    w._on_export_bed_fixture()

    txt = next(p for p in tmp_path.iterdir() if p.suffix == ".txt")
    body = txt.read_text(encoding="utf-8")
    assert "pin 1" in body and "pin 3" in body
    assert "DO NOT move the XY origin" in body
