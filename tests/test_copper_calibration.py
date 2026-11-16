"""Native vector calibration: preview, emitted paths, staged firing and records."""
import json
from pathlib import Path
import re

import pytest
from PySide6.QtCore import QSettings

from gerber2rml.engine import copper_calibration as cc, xtool
from gerber2rml.gui2 import stencil_laser as sl
from gerber2rml.gui2.copper_calibration import CopperCalibrationDialog


def test_single_lines_are_separate_open_vectors_without_an_outline_cut():
    coupon = cc.make_coupon()
    assert len(coupon.cells) == 5
    for paths in coupon.cells:
        assert len(paths) == 1 and len(paths[0]) == 2
        assert xtool._length(paths[0]) == 12
    job = cc.vector_job(coupon.cells[2], power=15, speed=1800, frequency=25)
    assert job.passes == 1
    assert job.zone_paths == [coupon.cells[2]]
    assert job.text.count('G1X') == 1
    assert 'G22' in job.text and 'G0Q25' in job.text
    assert 'S150F108000' in job.text
    assert job.seconds == pytest.approx(12/1800)


def test_spacing_is_derived_from_measured_removal_width():
    coupon = cc.make_coupon('Spacing', width=.04)
    pitches = []
    for cell in coupon.cells:
        pitch = cell[1][0][1] - cell[0][0][1]
        pitches.append(pitch)
        assert cell[-1][0][1] - cell[0][0][1] >= .25 - 1e-9
    assert pitches == pytest.approx([.016, .022, .028, .034, .040])


@pytest.mark.parametrize('stage,width,pitch', [('Spacing', 0, 0),
    ('Spacing', float('nan'), 0), ('Corners and pads', .04, 0),
    ('Corners and pads', .04, .05)])
def test_later_stages_require_measurements(stage, width, pitch):
    with pytest.raises(ValueError):
        cc.make_coupon(stage, width=width, pitch=pitch)


def test_corners_use_production_concentric_generation():
    coupon = cc.make_coupon('Corners and pads', width=.035, pitch=.02, rings=6)
    assert len(coupon.cells) == 5
    assert all(len(paths) >= 6 for paths in coupon.cells)
    for paths in coupon.cells:
        assert all(path[0] == path[-1] for path in paths)
        assert all(0 < x < cc.SIZE and 0 < y < cc.SIZE for p in paths for x,y in p)


@pytest.fixture
def dialog(qt_app, monkeypatch):
    monkeypatch.setattr(sl, '_SETTINGS', ('SRM-CAM-tests', 'copper-calibration'))
    QSettings(*sl._SETTINGS).clear()
    d = CopperCalibrationDialog()
    yield d
    d.close()


def test_calibration_opens_without_firing_or_inheriting_production_recipe(dialog):
    d = dialog
    assert d.kind == 'calibration'
    assert d.power.value() == 10 and d.speed.value() == 2000
    assert d.recipe().passes == 1
    assert d.passes.minimum() == d.passes.maximum() == 1
    assert d.job_switch.isHidden()
    assert not d.cut_btn.isEnabled()
    d.fresh_stage.setChecked(True)
    assert d.cut_btn.isEnabled()
    assert d.selected == {0}
    assert 'ONE pass' in d.cut_btn.text()
    assert d._make_job().passes == 1


def test_exact_preview_vectors_match_emitted_job_after_rotation(dialog):
    d = dialog
    d._turn_to(1, 2.5)
    d.coupon_cell.setCurrentIndex(3)
    paths = d._paths_on_bed()
    assert len(paths) == 1
    drawn = d.item.holes[3].path()
    for i, (x, y) in enumerate(paths[0]):
        element = drawn.elementAt(i)
        assert (element.x+d.x.value(), element.y+d.y.value()) == pytest.approx((x,y))
    job = d._make_job()
    assert job.zone_paths == [paths]
    assert job.text.count('G1X') == 1
    assert d.selected == {3}


def test_invalid_stage_does_not_sneak_old_geometry_into_a_run(dialog):
    d = dialog
    d.coupon_stage.setCurrentText('Spacing')
    assert d.coupon_stage.currentText() == 'Single lines'
    assert 'measured' in d.status.text()
    d.measured_width.setValue(.04)
    d.fresh_stage.setChecked(True)
    d.coupon_stage.setCurrentText('Spacing')
    assert not d.fresh_stage.isChecked() and not d.cut_btn.isEnabled()
    d.fresh_stage.setChecked(True)
    assert d.cut_btn.isEnabled()
    d.measured_width.setValue(0)
    assert not d.cut_btn.isEnabled()


class FakeLaser:
    def __init__(self):
        self.calls = []
        self.error = False
    def z(self):
        return 14.3
    def run(self, text):
        self.calls.append(text)
        if self.error:
            raise xtool.LaserError('connection lost after upload; exposure uncertain')
    def wait(self, *args, **kwargs):
        pass
    def stop(self):
        pass


def synchronous_run(d, monkeypatch):
    def start(fn, text, done):
        d._busy(True)
        try:
            result = fn(lambda _t: None)
        except Exception as e:
            d._done(str(e), True)
        else:
            d._done(done(result), False)
    monkeypatch.setattr(d, '_start', start)


def test_single_cell_run_records_exact_exposure_and_observation(dialog, monkeypatch):
    d = dialog
    d.laser = FakeLaser()
    synchronous_run(d, monkeypatch)
    d.photo_after.setChecked(False)
    d.fresh_stage.setChecked(True)
    d.coupon_cell.setCurrentIndex(2)
    d.power.setValue(23)
    d.speed.setValue(1750)
    d.freq.setValue(28)
    d.cut()
    assert len(d.laser.calls) == 1
    record = d._latest
    assert record['status'] == 'completed'
    assert record['cell'] == 3 and record['passes_requested'] == 1
    assert record['power_percent'] == 23 and record['speed_mm_s'] == 1750
    assert record['frequency_khz'] == 28 and record['head_z_mm'] == 14.3
    assert Path(record['gcode_path']).read_bytes().decode('ascii') == d.laser.calls[0]
    assert '1 completed passes' in d.count_note.text()
    d.result.setCurrentText('Copper remains')
    d.notes.setText('No continuous cleared substrate yet')
    d.record_observation()
    saved = json.loads(Path(record['record_path']).read_text())
    assert saved['observation'] == 'Copper remains'
    d.cut()
    assert '2 completed passes' in d.count_note.text()
    d.coupon_cell.setCurrentIndex(3)
    assert '0 completed passes' in d.count_note.text()


def test_uncertain_attempt_is_not_counted_as_a_complete_pass(dialog, monkeypatch):
    d = dialog
    d.laser = FakeLaser()
    d.laser.error = True
    synchronous_run(d, monkeypatch)
    d.photo_after.setChecked(False)
    d.fresh_stage.setChecked(True)
    d.cut()
    assert d._latest['status'] == 'failed_or_partial'
    assert '0 completed passes' in d.count_note.text()
    d.save_measured_recipe()
    assert not QSettings(*sl._SETTINGS).value('presets_traces', '')


def test_only_tested_uniform_exposure_can_be_saved_as_production_recipe(dialog, monkeypatch):
    d = dialog
    d.laser = FakeLaser()
    synchronous_run(d, monkeypatch)
    d.photo_after.setChecked(False)
    d.measured_width.setValue(.035)
    d.tested_pitch.setValue(.02)
    d.coupon_stage.setCurrentText('Corners and pads')
    d.fresh_stage.setChecked(True)
    # One successful shape is insufficient to qualify corners and pads.
    d.cut()
    d.result.setCurrentText('Clean isolation')
    d.record_observation()
    d.save_measured_recipe()
    assert 'all five' in d.status.text()
    d.cut()
    d.result.setCurrentText('Clean isolation')
    d.record_observation()
    for cell in range(1, 5):
        d.coupon_cell.setCurrentIndex(cell)
        d.cut()
        d.cut()
        d.result.setCurrentText('Clean isolation')
        d.record_observation()
    monkeypatch.setattr('gerber2rml.gui2.copper_calibration.QInputDialog.getText',
                        lambda *a, **k: ('My tested vectors', True))
    d.save_measured_recipe()
    assert QSettings(*sl._SETTINGS).value('presets_traces'), (d.status.text(), d._latest)
    presets = json.loads(QSettings(*sl._SETTINGS).value('presets_traces'))
    recipe = presets['My tested vectors']
    assert recipe['passes'] == 1 and recipe['kerf'] == .035
    assert recipe['_calibration']['qualifying_passes_with_manual_inspection'] == 2
    assert recipe['lines_per_cm'] == 500 and recipe['strategy'] == 'concentric'
    assert not recipe['spot_drills'] and not recipe['mark_outline']
    d.speed.setValue(2100)
    d.cut()
    d.result.setCurrentText('Clean isolation')
    d.record_observation()
    d.save_measured_recipe()
    assert 'mixed exposures' in d.status.text()


def test_measured_width_and_fine_pitch_survive_loading_in_production(dialog):
    from shapely.geometry import box
    saved = {'Measured': dict(strategy='concentric', power=23, speed=1750,
                              frequency=28, passes=2, offsets=6, kerf=.035,
                              lines_per_cm=2000, spot_drills=False, cross_hatch=False,
                              one_way=True, mark_outline=False, mark_power=10, rest_s=0)}
    QSettings(*sl._SETTINGS).setValue('presets_traces', json.dumps(saved))
    art = xtool.LaserArt(kind='traces', apertures=[], outline=box(0,0,20,20),
                         copper=box(3,3,17,17))
    d = sl.StencilLaserDialog(art)
    try:
        d.preset.setCurrentText('Measured')
        assert d.recipe().kerf == .035
        assert d.recipe().stepover == .005
        assert d.recipe().passes == 2
    finally:
        d.close()
