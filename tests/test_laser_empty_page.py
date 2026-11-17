"""The laser page with nothing loaded: a calibration area, and a Gerber folder
or a DXF loaded from the page itself."""
from pathlib import Path

import pytest

from gerber2rml.engine import xtool
from gerber2rml.gui2 import stencil_laser as sl
from test_laser_alignment import _scene

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "laser_proof_test"


@pytest.fixture
def page(qt_app, monkeypatch):
    monkeypatch.setattr(sl, "_SETTINGS", ("SRM-CAM-tests", "empty-page"))
    d = sl.StencilLaserDialog()
    d.x.setValue(50)
    d.y.setValue(60)
    yield d
    d._set_offset((0.0, 0.0))
    d.close()


def test_it_opens_with_nothing_loaded(page):
    assert page._empty and page.kind == "traces"
    assert page.name_lbl.text() == "No job loaded"
    assert page.art.size == xtool.CALIBRATION_AREA
    assert not page.empty_hint.isHidden() and not page.empty_cal_btn.isHidden()
    assert not page.proof_btn.isHidden()
    assert page.proof_btn.text() == "Calibrate the camera"
    assert page.rework_section.isHidden()


def test_nothing_is_etched_with_nothing_loaded(page):
    fired = []
    page.laser = type("L", (), {"run": lambda self, t: fired.append(t)})()
    page.cut()
    assert not fired and "Nothing loaded" in page.status.text()


def test_the_marks_go_inside_the_area():
    art = xtool.calibration_art()
    plan = xtool.proof_in_area(art, (50.0, 60.0))
    assert plan.where == "area" and len(plan.marks) == 3
    from shapely.geometry import box
    area = box(50, 60, 90, 90)
    assert all(area.contains(m) for m in plan.marks)


def test_the_calibration_runs_on_the_area(page, monkeypatch):
    err = (0.5, -0.7)

    class Laser:
        fired = None

        def run(self, text):
            Laser.fired = text

        def wait(self, *_a, **_k):
            pass

    page.laser = Laser()
    page._set_offset((0.0, 0.0))
    plan = page._proof_plans()[0][0]
    from shapely.geometry import box
    stock = box(20, 30, 140, 130)

    def photo(px_per_mm=sl._PX_PER_MM, raw=None, offset=None):
        raw = page._raw_photo() if raw is None else raw
        o = page.cam_offset if offset is None else offset
        size = int(220 * px_per_mm)
        return _scene((size, size), px_per_mm, dark=[],
                      marks=plan.marks if raw == "after" else [],
                      shift=(err[0] - o[0], err[1] - o[1]), sheet=stock)
    monkeypatch.setattr(page, "_raw_photo",
                        lambda: "after" if Laser.fired else "before")
    monkeypatch.setattr(page, "_photo", photo)
    monkeypatch.setattr(page, "_start", lambda fn, text, done=None:
                        page._say(done(fn(lambda *_a: None))))
    page.proof()
    assert page.cam_offset == pytest.approx(err, abs=0.08), page.status.text()
    assert "calibration area" in page.status.text()


def test_a_gerber_folder_is_opened_from_the_page(page, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(EXAMPLE)))
    page.open_gerber()
    assert not page._empty and page.kind == "traces"
    assert page.name_lbl.text() == EXAMPLE.name
    assert len(page.base_art.drills) == 12
    assert page.empty_hint.isHidden() and not page.rework_section.isHidden()
    assert page.proof_btn.text() == "Calibrate and lock onto the holes"
    page.switch_kind("silk")            # the folder's other jobs are there too
    assert page.kind in ("silk", "traces")


def test_a_dxf_is_opened_from_the_empty_page(page):
    from gerber2rml.engine import dxf_traces
    p = EXAMPLE / "proof.dxf"
    page.load_dxf_art(dxf_traces.build_dxf_traces(p), p)
    assert not page._empty and len(page.base_art.drills) == 12
    assert page.empty_hint.isHidden()
