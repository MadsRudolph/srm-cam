"""The photo and rework features ported from the original interface into the
setup sheet: a per-box "level" flag, probing the boxes, proposing boxes from
the photo, the photo sliders, hand-picked anchor holes, the phone photo's
auto-crop, the 3D view of only the re-cut, and the photo in the setup file.

Nothing here opens a serial port: the probe run is exercised on its pure
half (``deepen_from_probe``) and its refusals, the same way the levelling
page is tested.
"""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import QFileDialog, QPushButton, QTableWidgetItem

from gerber2rml.gui2 import dialogs, photo as photo_mod, rework
from gerber2rml.gui2.window import MainWindow
from gerber2rml.engine.leveling import HeightMap
from gerber2rml.toolpath import Move

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


def _give_a_map(win, dz=0.0):
    """A 2x2 probed grid on the board, switched on, every point at ``dz``."""
    page = win.level_page
    page.nx.setValue(2)
    page.ny.setValue(2)
    page._build()
    for r in range(page.table.rowCount()):
        page.table.setItem(r, 2, QTableWidgetItem(f"{dz:.4f}"))
    page.use_chk.setChecked(True)
    assert page.height_map("bottom") is not None
    return page


def _photo_file(path, w=60, h=40):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(184, 115, 51))
    assert img.save(str(path))
    return str(path)


def _lay_photo(win, path):
    """A synthetic photo laid over the whole work, corner to corner."""
    x0, y0, x1, y1 = win.work_bounds()
    img = win.decode_photo(path)
    hh, ww = img.shape[:2]
    photo_pts = [(0, 0), (ww, 0), (ww, hh), (0, hh)]
    machine_pts = [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
    return win._apply_photo(img, photo_pts, machine_pts, path)


# --- the per-box level flag ------------------------------------------------

def test_a_new_box_follows_the_map_only_when_there_is_one(loaded):
    page = loaded.rework_page
    page.add_region(10, 10, 20, 15)
    assert page.follows() == [False]
    _give_a_map(loaded)
    page.add_region(30, 10, 40, 15)
    assert page.follows() == [False, True]
    assert page.table.columnCount() == 6
    assert page.table.item(1, 5).checkState() == Qt.Checked
    # Unticking in the table is the per-box override.
    page.table.item(1, 5).setCheckState(Qt.Unchecked)
    assert page.follows() == [False, False]
    page.table.item(0, 5).setCheckState(Qt.Checked)
    assert page.follows() == [True, False]


def test_the_level_flag_survives_a_setup_save_and_load(loaded, tmp_path,
                                                        monkeypatch):
    page = loaded.rework_page
    page.add_region(10, 10, 20, 15, follow=True)
    page.add_region(30, 10, 40, 15, follow=False)
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_save_setup()
    data = json.loads(path.read_text())
    # The regions entry is still the five numbers an older build wrote.
    assert data["rework"]["regions"] == [[10, 10, 20, 15, 0.25],
                                         [30, 10, 40, 15, 0.25]]
    assert data["rework"]["follow"] == [True, False]
    page._clear()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_load_setup()
    assert loaded.rework_page.follows() == [True, False]
    assert loaded.rework_page.table.rowCount() == 2


def test_removing_a_box_removes_its_flag_with_it(loaded):
    page = loaded.rework_page
    page.add_region(10, 10, 20, 15, follow=True)
    page.add_region(30, 10, 40, 15, follow=False)
    page.table.selectRow(0)
    page._remove()
    assert page._regions == [(30, 10, 40, 15, 0.25)]
    assert page.follows() == [False]


def _run(x0, x1, y, z=-0.2):
    return [Move(x0, y, 1.0, True), Move(x0, y, z, False), Move(x1, y, z, False)]


def test_clip_boxes_warps_only_the_boxes_that_follow():
    paths = [_run(0, 100, 5)]
    hmap = HeightMap(lambda x, y: 0.1)                # the copper sits 0.1 high
    boxes = [((0, 0, 10, 10, 0.3), True), ((20, 0, 30, 10, 0.3), False)]
    clipped, n = rework.clip_boxes(paths, boxes, hmap=hmap)
    assert n == 1
    cut_z = sorted({round(m.z, 3) for tp in clipped for m in tp if not m.rapid})
    # The following box rides up by the map; the flat one is at its depth.
    assert cut_z == [-0.3, -0.2]


def test_clip_boxes_without_a_map_leaves_every_box_flat():
    paths = [_run(0, 100, 5)]
    boxes = [((0, 0, 10, 10, 0.3), True)]
    clipped, n = rework.clip_boxes(paths, boxes, hmap=None)
    assert n == 0
    assert {round(m.z, 3) for tp in clipped for m in tp if not m.rapid} == {-0.3}


# --- probing the boxes -----------------------------------------------------

def test_deepen_from_probe_deepens_where_the_copper_is_lower():
    regions = [(0, 0, 10, 10, 0.2), (20, 0, 30, 10, 0.2), (40, 0, 50, 10, 0.2)]
    flat = HeightMap(lambda x, y: 0.0)
    results = [{"id": 0, "z": 1000},
               {"id": 1, "z": 950},          # 0.05 mm LOWER than the map said
               {"id": 2, "z": 1040},         # higher: the cut was already deep
               {"id": 3, "z": None, "error": "timeout"}]
    new, deepened, skipped = rework.deepen_from_probe(regions, results, flat,
                                                      (0.0, 0.0))
    assert [r[4] for r in new] == [0.25, 0.2, 0.2]
    assert deepened == [(0, pytest.approx(0.05))]
    assert skipped == 1


def test_deepen_from_probe_reads_against_the_map_not_against_zero():
    """The map is relative to its own first point; so is the probe. A plane
    that says the box is 0.1 high, and a probe that finds it 0.1 high, is a
    box that needs nothing."""
    regions = [(0, 0, 10, 10, 0.2)]
    tilted = HeightMap(lambda x, y: 0.02 * x)          # 0.1 high at x = 5
    results = [{"id": 0, "z": 0}, {"id": 1, "z": 100}]
    new, deepened, skipped = rework.deepen_from_probe(regions, results, tilted,
                                                      (0.0, 0.0))
    assert deepened == [] and skipped == 0
    assert new == regions


def test_deepen_from_probe_needs_the_reference():
    assert rework.deepen_from_probe([(0, 0, 10, 10, 0.2)],
                                    [{"id": 1, "z": 5}],
                                    HeightMap(lambda x, y: 0.0), (0, 0)) is None


def test_probe_boxes_refuses_politely_without_a_link(loaded, monkeypatch):
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append((lvl, txt)))
    page = loaded.rework_page
    page._probe_boxes()
    assert said and "Draw a box" in said[-1][1]
    page.add_region(10, 10, 20, 15)
    page._probe_boxes()
    assert "Connect" in said[-1][1]
    assert page.probe_btn.isEnabled()


def test_the_probe_summary_lands_in_the_table(loaded):
    page = loaded.rework_page
    page.add_region(10, 10, 20, 15)
    page.add_region(30, 10, 40, 15)
    text = page.apply_probe_results(
        [{"id": 0, "z": 0}, {"id": 1, "z": -30}, {"id": 2, "z": 0}],
        hmap=HeightMap(lambda x, y: 0.0), ref=(0.0, 0.0))
    assert "1 of 2 boxes deepened" in text
    assert page._regions[0][4] == pytest.approx(0.28)
    assert page.table.item(0, 4).text() == "0.28"


# --- the tier ---------------------------------------------------------------

def test_the_probe_and_the_detector_are_full_only(loaded, monkeypatch):
    page = loaded.rework_page
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    page.sync_tier()
    assert page.probe_section.isHidden() and page.detect_btn.isHidden()
    assert not page.export_btn.isHidden()
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    page.sync_tier()
    assert not page.probe_section.isHidden() and not page.detect_btn.isHidden()


# --- the 3D view of the re-cut -------------------------------------------------

def test_the_rework_3d_view_plays_only_the_boxes(loaded, monkeypatch):
    opened = []
    monkeypatch.setattr(loaded, "open_sim3d",
                        lambda paths, title: opened.append((paths, title)))
    page = loaded.rework_page
    # A box that certainly holds some cutting: around a point of the pass.
    m = next(m for tp in page._source_paths("traces") for m in tp if not m.rapid)
    bx0, by0, bx1, by1 = m.x - 4, m.y - 4, m.x + 4, m.y + 4
    page.add_region(bx0, by0, bx1, by1)
    page._watch_in_3d()
    assert len(opened) == 1
    paths, title = opened[0]
    assert "rework" in title and paths
    for tp in paths:
        for m in tp:
            if not m.rapid:
                assert bx0 - 1e-6 <= m.x <= bx1 + 1e-6
                assert by0 - 1e-6 <= m.y <= by1 + 1e-6


def test_the_3d_view_says_so_when_nothing_is_boxed(loaded, monkeypatch):
    said, opened = [], []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append(txt))
    monkeypatch.setattr(loaded, "open_sim3d",
                        lambda paths, title: opened.append(title))
    loaded.rework_page._watch_in_3d()
    assert not opened and "Draw a box" in said[-1]


# --- the photo sliders --------------------------------------------------------

def test_the_photo_sliders_drive_the_stage(loaded, tmp_path):
    assert not loaded.photo_controls_act.isEnabled()
    _lay_photo(loaded, _photo_file(tmp_path / "board.png"))
    assert loaded.photo_controls_act.isEnabled()
    assert loaded.stage._photo_alpha == 1.0 and loaded.stage._photo_dim == 0.55
    loaded.photo_controls.opacity.setValue(40)
    loaded.photo_controls.dim.setValue(80)
    assert loaded.stage._photo_alpha == pytest.approx(0.4)
    assert loaded.stage._photo_dim == pytest.approx(0.8)
    loaded.action_clear_photo()
    assert not loaded.photo_controls_act.isEnabled()
    assert loaded.stage._photo_dim == 0.0
    # The values are the operator's preference and come back with the next photo.
    _lay_photo(loaded, _photo_file(tmp_path / "board2.png"))
    assert loaded.stage._photo_alpha == pytest.approx(0.4)
    assert loaded.stage._photo_dim == pytest.approx(0.8)


def test_the_slider_widget_sits_at_the_end_of_the_photo_group(win):
    view = [m for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))
            if m.title() == "&View"][0]
    acts = view.actions()
    texts = [a.text() for a in acts]
    i = texts.index("Take the photo off")
    assert texts[i + 1] == "Choose which holes anchor the photo…"
    assert acts[i + 2] is win.photo_controls_act
    # The photo group ends with the sliders; whatever follows (the measure
    # tool and the file simulator, added later) starts after a separator.
    assert i + 2 == len(acts) - 1 or acts[i + 3].isSeparator()


# --- hand-picked anchor holes -----------------------------------------------------

def test_anchor_spread_tells_a_line_from_a_rectangle():
    assert photo_mod.anchor_spread([(0, 0), (20, 0), (20, 10), (0, 10)]) == pytest.approx(10.0)
    assert photo_mod.anchor_spread([(0, 0), (10, 0.1), (20, 0), (30, 0.1)]) < 1.0
    assert photo_mod.anchor_spread([(0, 0)]) == 0.0


def test_snap_picks_matches_holes_or_gives_up():
    holes = [(0, 0, 0.8), (10, 0, 0.8), (10, 10, 0.8), (0, 10, 0.8), (5, 5, 0.8)]
    picks = [(0.1, 0.0), (10.0, 0.1), (10.0, 10.0), (0.0, 9.9)]
    assert photo_mod.snap_picks(picks, holes) == [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert photo_mod.snap_picks([(0, 0), (10, 0), (10, 10), (3, 3)], holes) is None
    assert photo_mod.snap_picks([(0, 0), (10, 0), (10, 10)], holes) is None
    assert photo_mod.snap_picks([(0, 0), (0.1, 0), (10, 10), (0, 10)], holes) is None


def test_the_hole_picker_wants_four_spread_holes(qt_app):
    holes = [(0, 0, 0.8), (30, 0, 0.8), (30, 20, 0.8), (0, 20, 0.8),
             (10, 0, 0.8), (20, 0, 0.8)]
    dlg = photo_mod.HolePickDialog(None, holes)
    dlg.canvas.resize(600, 400)
    ok = dlg.ok_btn
    assert not ok.isEnabled()
    for x, y in [(0, 0), (10, 0), (20, 0), (30, 0)]:
        assert dlg.canvas.pick_at(dlg.canvas.to_px(x, y))
    assert not ok.isEnabled()                       # four, but in a line
    assert "in a line" in dlg.prompt.text()
    dlg.canvas.undo()
    assert dlg.canvas.pick_at(dlg.canvas.to_px(30, 20))
    assert ok.isEnabled()
    assert dlg.anchors() == [(0, 0), (10, 0), (20, 0), (30, 20)]
    # Empty board, and a hole already picked, are not picks.
    assert not dlg.canvas.pick_at(dlg.canvas.to_px(15, 10))
    assert not dlg.canvas.pick_at(dlg.canvas.to_px(0, 0))
    assert isinstance(dlg, dialogs.Sheet)
    dlg.close()


def test_the_hole_picker_reopens_with_the_last_picks(qt_app):
    holes = [(0, 0, 0.8), (30, 0, 0.8), (30, 20, 0.8), (0, 20, 0.8)]
    dlg = photo_mod.HolePickDialog(None, holes,
                                   preset=[(0.05, 0), (30, 0), (30, 20), (0, 20)])
    assert dlg.anchors() == [(0, 0), (30, 0), (30, 20), (0, 20)]
    assert dlg.ok_btn.isEnabled()
    dlg.close()


def test_chosen_anchors_are_used_while_they_still_fit_the_board(loaded, monkeypatch):
    holes = list(loaded.state.board.holes)
    auto = photo_mod.pick_anchor_holes(holes)
    # Any four other holes, chosen the way the dialog would.
    picks = [(h[0], h[1]) for h in holes if (h[0], h[1]) not in auto][:4]
    if len(picks) < 4:
        picks = list(reversed(auto))
    loaded._photo_anchor_pts = picks
    anchors, chosen = loaded.photo_anchors(holes)
    assert chosen and anchors == picks
    # A pick that is off every hole means the board moved: back to automatic.
    loaded._photo_anchor_pts = picks[:3] + [(picks[3][0] + 5.0, picks[3][1])]
    anchors, chosen = loaded.photo_anchors(holes)
    assert not chosen and anchors == auto


def test_the_anchor_dialog_marks_the_bed_and_the_setup_file(loaded, tmp_path,
                                                            monkeypatch):
    holes = list(loaded.state.board.holes)
    picks = [(h[0], h[1]) for h in holes[:4]]
    monkeypatch.setattr(photo_mod.HolePickDialog, "exec", lambda self: 1)
    monkeypatch.setattr(photo_mod.HolePickDialog, "anchors",
                        lambda self: list(picks))
    loaded.action_photo_anchors()
    assert loaded._photo_anchor_pts == picks
    assert loaded.stage._photo_anchors == picks
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_save_setup()
    data = json.loads(path.read_text())
    assert data["photo"]["anchors"] == [list(p) for p in picks]
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_load_setup()
    assert loaded._photo_anchor_pts == picks
    assert loaded.stage._photo_anchors == picks


def test_a_new_board_forgets_the_chosen_anchors(loaded):
    loaded._photo_anchor_pts = [(1, 1), (2, 2), (3, 3), (4, 4)]
    loaded.stage.set_photo_anchors(loaded._photo_anchor_pts)
    loaded.load_folder(str(FIXT))
    assert loaded._photo_anchor_pts is None
    assert loaded.stage._photo_anchors == []


# --- the photo in the setup file -------------------------------------------

def test_the_photo_survives_a_setup_save_and_load(loaded, tmp_path, monkeypatch):
    src = _photo_file(tmp_path / "shot.png")
    _lay_photo(loaded, src)
    loaded.photo_controls.opacity.setValue(70)
    loaded.photo_controls.dim.setValue(30)
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_save_setup()
    data = json.loads(path.read_text())
    ph = data["photo"]
    assert ph["path"] == src
    assert len(ph["photo_pts"]) == 4 and len(ph["machine_pts"]) == 4
    assert ph["opacity"] == pytest.approx(0.7) and ph["dim"] == pytest.approx(0.3)
    assert (tmp_path / ph["copy"]).is_file()

    loaded.action_clear_photo()
    assert not loaded.stage.has_photo()
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_load_setup()
    assert loaded.stage.has_photo()
    assert loaded.photo_overlay()["path"] == src
    assert loaded.stage._photo_alpha == pytest.approx(0.7)
    assert loaded.stage._photo_dim == pytest.approx(0.3)
    assert loaded.photo_controls.values() == (pytest.approx(0.7), pytest.approx(0.3))

    # The original gone, the copy beside the setup still restores it.
    Path(src).unlink()
    loaded.action_clear_photo()
    loaded.action_load_setup()
    assert loaded.stage.has_photo()
    assert loaded.photo_overlay()["path"] == str(tmp_path / ph["copy"])

    # Both gone: the load says so instead of failing.
    (tmp_path / ph["copy"]).unlink()
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append((lvl, txt)))
    loaded.action_clear_photo()
    loaded.action_load_setup()
    assert not loaded.stage.has_photo()
    assert said[-1][0] == "warn" and "the photo" in said[-1][1]


def test_a_setup_without_a_photo_loads_as_before(loaded, tmp_path, monkeypatch):
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_save_setup()
    data = json.loads(path.read_text())
    assert data["photo"] == {"anchors": [], "opacity": 1.0, "dim": 0.55}
    del data["photo"]
    path.write_text(json.dumps(data))
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append((lvl, txt)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_load_setup()
    assert said[-1] == ("ok", "Setup loaded.")


# --- the phone photo's auto-crop ------------------------------------------------

def _scene(path, board, w=800, h=600):
    """A phone shot: grey machine, a pink-brown copper blank somewhere in it."""
    rng = np.random.default_rng(7)
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (70, 72, 75)
    x0, y0, x1, y1 = board
    img[y0:y1, x0:x1] = (185, 142, 128)
    img = np.clip(img.astype(np.int16) + rng.integers(-6, 6, img.shape),
                  0, 255).astype(np.uint8)
    q = QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_RGB888)
    assert q.copy().save(str(path))
    return str(path)


def test_a_phone_shot_is_cropped_to_the_copper(tmp_path):
    from gerber2rml.gui2.phonephoto import autocrop_to_copper
    src = _scene(tmp_path / "phone.png", (160, 120, 680, 500))
    out = autocrop_to_copper(src)
    assert out != src and out.endswith("_crop.jpg")
    q = QImage(out)
    assert 480 <= q.width() <= 580 and 340 <= q.height() <= 440


def test_a_shot_that_is_all_board_is_left_alone(tmp_path):
    from gerber2rml.gui2.phonephoto import autocrop_to_copper
    src = _scene(tmp_path / "tight.png", (0, 0, 800, 600))
    assert autocrop_to_copper(src) == src
    assert autocrop_to_copper(str(tmp_path / "missing.jpg")) == str(tmp_path / "missing.jpg")


def test_the_phone_hand_off_crops_before_anchoring(loaded, tmp_path, monkeypatch):
    src = _scene(tmp_path / "phone.png", (160, 120, 680, 500))

    class _Dlg:
        def __init__(self, *a, **k):
            self.photo_path = src

        def exec(self):
            return 1

    from gerber2rml.gui2 import phonephoto
    monkeypatch.setattr(phonephoto, "PhonePhotoDialog", _Dlg)
    got = []
    monkeypatch.setattr(loaded, "action_load_photo",
                        lambda photo_path=None: got.append(photo_path))
    loaded.action_phone_photo()
    assert got and got[0].endswith("_crop.jpg")


# --- proposing boxes from the photo ----------------------------------------------

def test_detect_says_what_is_missing(loaded, monkeypatch):
    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append(txt))
    page = loaded.rework_page
    page._detect_from_photo()
    assert "Lay a photo" in said[-1]


def test_detect_from_the_photo_proposes_a_box_over_an_uncut_stretch(
        loaded, tmp_path, monkeypatch):
    """A synthetic straight-down shot of the cut board: every isolation
    channel bright (cut), except one stretch left copper-coloured."""
    from gerber2rml.app.preview import toolpath_segments
    page = loaded.rework_page
    # One isolation pass: the detector reads a channel against the copper
    # either side of it, and a three-pass band is bright wall to wall.
    loaded.state.trace.offsets = 1
    loaded._paths_cache = {}
    paths = page._source_paths("traces")
    channels = [c for c in toolpath_segments(paths)[0] if len(c) >= 2]
    assert channels
    x0, y0, x1, y1 = loaded.work_bounds()
    ppm = 16
    W, H = int(round((x1 - x0) * ppm)), int(round((y1 - y0) * ppm))
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor(184, 115, 51))                      # copper
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, False)
    pen = QPen(QColor(235, 232, 220))                   # a cut, catching light
    pen.setWidthF(1.0 * ppm)
    p.setPen(pen)
    from PySide6.QtCore import QPointF
    to_px = lambda x, y: QPointF((x - x0) * ppm, (y1 - y) * ppm)
    for c in channels:
        for (ax, ay), (bx, by) in zip(c, c[1:]):
            p.drawLine(to_px(ax, ay), to_px(bx, by))
    # A patch in the middle of the board the cutter never reached: every
    # channel through it still copper. (Not at the edge - channels along
    # the outline belong to the cut-out and the detector drops them.)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    mx, my = min((pt for c in channels for pt in c),
                 key=lambda pt: (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(184, 115, 51))
    from PySide6.QtCore import QRectF
    p.drawRect(QRectF(to_px(mx - 5, my + 5), to_px(mx + 5, my - 5)))
    p.end()
    src = str(tmp_path / "cut.png")
    assert img.save(src)
    _lay_photo(loaded, src)

    said = []
    monkeypatch.setattr(loaded, "say", lambda lvl, txt: said.append((lvl, txt)))
    monkeypatch.setattr(dialogs, "report_error",
                        lambda *a, **k: pytest.fail(f"refused: {a[1:]}"))
    page._detect_from_photo()
    assert page._regions, said
    hit = [r for r in page._regions
           if r[0] <= mx <= r[2] and r[1] <= my <= r[3]]
    assert hit, (page._regions, (mx, my))
    assert "boxed" in said[-1][1]
