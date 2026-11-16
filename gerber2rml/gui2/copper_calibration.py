"""Staged copper experiments using the production native vector writer."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QBrush, QPainterPath
from PySide6.QtWidgets import QCheckBox, QGraphicsItem, QInputDialog, QLineEdit, QComboBox

from gerber2rml.engine import copper_calibration as cc, xtool
from gerber2rml.gui import workspace
from gerber2rml.gui2 import theme, widgets
from gerber2rml.gui2 import stencil_laser as sl


class CopperCalibrationDialog(sl.StencilLaserDialog):
    def __init__(self, parent=None, laser=None):
        self._coupon = cc.make_coupon()
        self._cell = 0
        self._coupon_valid = True
        self._calibration_running = False
        self.saved_recipe_name = None
        self._records = []
        self._latest = None
        self._pending_record = None
        self._stopped = False
        self._sample_id = uuid.uuid4().hex
        super().__init__(self._coupon.artwork(), parent, laser=laser,
                         name="Native vector calibration · use fresh scrap")
        self.job_switch.hide()
        self.mode.hide()
        self.all_btn.hide()
        self.none_btn.hide()
        self.calibrate_btn.hide()
        self.reference_snap.setCurrentIndex(self.reference_snap.findData("free"))
        self.passes.setRange(1, 200)
        self.passes.setValue(1)
        self.mark.setChecked(False)
        self.photo_after.setChecked(True)
        self.set_look("outlines")

        recipe_section = self.preset.parentWidget()
        section = widgets.Section("Copper calibration")
        self.stage_hint = widgets.hint("")
        section.add(self.stage_hint)
        self.coupon_stage = QComboBox()
        self.coupon_stage.addItems(cc.STAGES)
        section.add(widgets.Field("Stage", self.coupon_stage))
        self.coupon_cell = QComboBox()
        self.cell_field = widgets.Field("Cell", self.coupon_cell)
        section.add(self.cell_field)
        # The exposure grid's axes: columns are speeds, rows are pass counts.
        self.grid_speeds = QLineEdit(", ".join(f"{v:g}" for v in cc.GRID_SPEEDS))
        self.grid_passes = QLineEdit(", ".join(str(n) for n in cc.GRID_PASSES))
        self.grid_speeds_field = widgets.Field("Speeds", self.grid_speeds, unit="mm/s",
                                               help="One column each, comma-separated.")
        self.grid_passes_field = widgets.Field("Passes", self.grid_passes,
                                               help="One row each. Every line in a row "
                                                    "gets that many passes.")
        section.add(self.grid_speeds_field)
        section.add(self.grid_passes_field)
        self.grid_speeds.editingFinished.connect(self._change_coupon)
        self.grid_passes.editingFinished.connect(self._change_coupon)
        self.material = QLineEdit("FR4 · 1.6 mm board · copper unknown")
        section.add(widgets.Field("Material", self.material))
        self.fresh_stage = QCheckBox("Fresh copper positioned for this stage")
        section.add(self.fresh_stage)
        self.fresh_stage.toggled.connect(self._sync_run_ready)
        self.measured_width = sl._spin(0, 0, .2, .001, 3, suffix=" mm")
        self.tested_pitch = sl._spin(0, 0, .2, .001, 3, suffix=" mm")
        self.test_rings = sl._ispin(6, 1, 12)
        self.width_field = widgets.Field(
            "Cleared width", self.measured_width,
            help="Measure the exposed substrate width of a line that actually cleared "
                 "the copper. Leave at zero until measured.")
        self.pitch_field = widgets.Field("Tested pitch", self.tested_pitch,
                                         help="After the spacing test, enter a pitch that "
                                              "gave continuous clearing.")
        self.rings_field = widgets.Field("Isolation rings", self.test_rings)
        for f in (self.width_field, self.pitch_field, self.rings_field):
            section.add(f)
        # Move the real exposure controls here; there is no separate XCS preset.
        for field in (self.power_field, self.speed_field, self.freq_field,
                      self.passes_field):
            section.add(field)
        self.count_note = widgets.hint("")
        section.add(self.count_note)
        self.result = QComboBox()
        self.result.addItems(["Not inspected", "Copper remains", "Clean isolation", "Laminate damage"])
        section.add(widgets.Field("Observation", self.result))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Measured width, resistance, corner condition…")
        section.add(self.notes)
        self.record_btn = widgets.button("Record observation", on=self.record_observation)
        section.add(self.record_btn)
        self.qualified_btn = widgets.button("Save measured recipe…", on=self.save_measured_recipe)
        section.add(self.qualified_btn)
        self.new_scrap_btn = widgets.button("New scrap / new sample", kind="ghost", on=self.new_sample)
        section.add(self.new_scrap_btn)
        section.add(widgets.hint("Each attempt saves its exact laser file, exposure, position, "
                                 "pass history and observation in SRM-CAM/exports/copper-calibration."))
        panel_layout = self.job_switch.parentWidget().layout()
        panel_layout.insertWidget(1, section)
        recipe_section.hide()
        self._coupon_controls = [self.coupon_stage, self.coupon_cell, self.material,
                                 self.grid_speeds, self.grid_passes,
                                 self.fresh_stage,
                                 self.measured_width, self.tested_pitch, self.test_rings,
                                 self.result, self.notes, self.record_btn,
                                 self.qualified_btn, self.new_scrap_btn]
        self.coupon_stage.currentTextChanged.connect(self._change_coupon)
        self.measured_width.valueChanged.connect(self._change_coupon)
        self.tested_pitch.valueChanged.connect(self._change_coupon)
        self.test_rings.valueChanged.connect(self._change_coupon)
        self.coupon_cell.currentIndexChanged.connect(self._change_cell)
        self.power.setValue(100)
        self.freq.setValue(30)
        self.passes.valueChanged.connect(lambda *_: self._paint())
        self._change_coupon()
        self._say("Put fresh scrap under the 40 × 40 mm square, autofocus on its copper, "
                  "tick 'Fresh copper positioned' and run the exposure grid.")

    # -- the exposure grid ------------------------------------------------------
    def _grid(self):
        return self._coupon.stage == cc.EXPOSURE

    @staticmethod
    def _numbers(text, kind):
        try:
            return [kind(float(t)) for t in text.replace(";", ",").split(",") if t.strip()]
        except ValueError:
            raise ValueError("Write the speeds and passes as numbers separated by commas.")

    def _paths_on_bed(self, cell=None):
        paths = self._coupon.cells[self._cell if cell is None else cell]
        return [[self._reference_to_bed((x, cc.SIZE-y)) for x, y in path] for path in paths]

    def _presets(self):
        return {name: sl._recipe_dict(recipe)
                for name, recipe in sl.KINDS["calibration"]["presets"].items()}, set()

    def _build_item(self):
        super()._build_item()
        self._coupon_labels = []
        grid = self._coupon.stage == cc.EXPOSURE
        if grid:
            xs, ys = cc.grid_layout(len(self._coupon.speeds), len(self._coupon.pass_counts))
            heads = [(f"{v:g}", (x + 1.0, 2.0)) for v, x in zip(self._coupon.speeds, xs)]
            heads += [(f"{n}×", (0.6, y - 1.0)) for n, y in zip(self._coupon.pass_counts, ys)]
            heads.append(("speed mm/s →   passes ↓", (0.0, -4.5)))
            for text, (lx, ly) in heads:
                x, y = self._reference_to_bed((lx, cc.SIZE - ly))
                label = self.scene.addSimpleText(text)
                label.setParentItem(self.item)
                label.setPos(x - self.x.value(), y - self.y.value())
                label.setBrush(sl._c(theme.TEXT_2))
                label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                label.setAcceptedMouseButtons(Qt.NoButton)
                self._coupon_labels.append(label)
        for i, hole in enumerate(self.item.holes):
            path = QPainterPath()
            for vector in self._paths_on_bed(i):
                for j, (x, y) in enumerate(vector):
                    p = QPointF(x-self.x.value(), y-self.y.value())
                    path.moveTo(p) if j == 0 else path.lineTo(p)
            hole.setPath(path)
            hole.setToolTip(f"Cell {i+1}: {self._coupon.labels[i]}")
            if grid:
                continue
            x, y = self._reference_to_bed((18, cc.SIZE-(5+i*7)))
            label = self.scene.addSimpleText(f"{i+1}  {self._coupon.labels[i]}")
            label.setParentItem(self.item)
            label.setPos(x-self.x.value(), y-self.y.value())
            label.setBrush(sl._c(theme.TEXT_2))
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            label.setAcceptedMouseButtons(Qt.NoButton)
            self._coupon_labels.append(label)
        self.selected = set(range(len(self._coupon.cells))) if grid else {self._cell}
        self._paint(estimate=False)

    def _paint(self, active=None, *, estimate=True):
        super()._paint(active, estimate=estimate)
        if self.item is not None:
            for hole in self.item.holes:
                hole.setBrush(QBrush(Qt.NoBrush))
        if self._coupon.stage == cc.EXPOSURE:
            n = sum(p for _v, p in self._coupon.exposures)
            self.cut_btn.setText(f"Run the exposure grid · {len(self._coupon.cells)} lines")
        else:
            n = self.passes.value()
            self.cut_btn.setText(f"Run cell {self._cell+1} · {n} pass{'' if n == 1 else 'es'}")

    def _estimate(self):
        if not hasattr(self, "time_read") or self.item is None:
            return
        try:
            job = self._make_job()
            self.time_read.set(f"{job.seconds:.2f} s")
        except ValueError:
            self.time_read.set("—")

    def _make_job(self):
        if self._coupon.stage == cc.EXPOSURE:
            cells = [self._paths_on_bed(i) for i in range(len(self._coupon.cells))]
            return cc.exposure_job(cells, self._coupon.exposures,
                                   power=self.power.value(), frequency=self.freq.value())
        return cc.vector_job(self._paths_on_bed(), power=self.power.value(),
                             speed=self.speed.value(), frequency=self.freq.value(),
                             passes=self.passes.value())

    def _change_coupon(self, *_a):
        stage = self.coupon_stage.currentText()
        try:
            coupon = cc.make_coupon(stage, width=self.measured_width.value(),
                                     pitch=self.tested_pitch.value(), rings=self.test_rings.value(),
                                     speeds=self._numbers(self.grid_speeds.text(), float),
                                     pass_counts=self._numbers(self.grid_passes.text(), int))
        except ValueError as e:
            self.coupon_stage.blockSignals(True)
            self.coupon_stage.setCurrentText(self._coupon.stage)
            self.coupon_stage.blockSignals(False)
            # Invalid measurements cannot leave an old, runnable geometry on screen.
            try:
                cc.make_coupon(self._coupon.stage, width=self.measured_width.value(),
                               pitch=self.tested_pitch.value(), rings=self.test_rings.value())
                self._coupon_valid = True
            except ValueError:
                self._coupon_valid = False
            self._sync_run_ready()
            return self._say(str(e), warn=True)
        self._coupon_valid = True
        changed_stage = coupon.stage != self._coupon.stage
        if changed_stage:
            self._sample_id = uuid.uuid4().hex
            self._latest = None
            self.fresh_stage.setChecked(False)
        self._coupon = coupon
        self._clear_references()
        self.base_art = coupon.artwork()
        self.art = xtool.rotated(self.base_art, self.turns, self.fine)
        self.coupon_cell.blockSignals(True)
        self.coupon_cell.clear()
        self.coupon_cell.addItems([f"{i+1} · {label}" for i, label in enumerate(coupon.labels)])
        self._cell = min(self._cell, len(coupon.cells)-1)
        self.coupon_cell.setCurrentIndex(self._cell)
        self.coupon_cell.blockSignals(False)
        self._populate_auto_references()
        self._build_item()
        self._show_stage_controls()
        self._update_count()
        self._sync_run_ready()
        if changed_stage:
            self._say("Move the coupon onto fresh copper for this stage, then confirm its position. "
                      "Keep the exposure used to measure the cleared width.")

    def _show_stage_controls(self):
        grid = self._grid()
        for w in (self.grid_speeds_field, self.grid_passes_field):
            w.setVisible(grid)
        for w in (self.cell_field, self.speed_field, self.passes_field,
                  self.width_field, self.pitch_field, self.rings_field, self.qualified_btn):
            w.setVisible(not grid)
        if grid:
            self.stage_hint.setText(
                "Columns are speeds, rows are pass counts, all at the power below; one "
                "6 mm line per cell, fired in one job. The passes go round-robin with a "
                "short laser-off rest each round, as on a real board. Afterwards find the "
                "cell that cleared the copper with the fewest passes and no charring, then "
                "use its speed and passes for the single-line stage.")
        else:
            self.stage_hint.setText(
                "Use the speed and passes the exposure grid found. Only the selected cell "
                "fires. Inspect and measure before the next stage. Labels and frame are "
                "guides, never lasered.")

    def _sync_run_ready(self, *_a):
        if hasattr(self, "fresh_stage"):
            self.cut_btn.setEnabled(self._coupon_valid and self.fresh_stage.isChecked()
                                   and not self._calibration_running)

    def _change_cell(self, index):
        if index < 0:
            return
        self._cell = index
        self.selected = {index}
        self._paint()
        self._update_count()

    def _geometry_key(self, paths=None):
        payload = {"sample": self._sample_id,
                   "paths": [[(round(x, 3), round(y, 3)) for x, y in p]
                             for p in (self._paths_on_bed() if paths is None else paths)]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _update_count(self):
        if not hasattr(self, "count_note"):
            return
        key = self._geometry_key()
        count = sum(r.get("passes_requested", 1) for r in self._records
                    if r["status"] == "completed" and r["geometry_key"] == key)
        if self._grid():
            self.count_note.setText("")
            return
        self.count_note.setText(f"Cell {self._cell+1}: {count} completed passes at this position "
                                "on this sample. Interrupted attempts are recorded separately.")

    def _write_record(self, record):
        path = Path(record["record_path"])
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def _fill(self):
        if not self.fresh_stage.isChecked():
            return self._say("Position fresh copper for this stage, then check its placement.", warn=True)
        try:
            # Revalidate input even if called through a keyboard/programmatic path.
            cc.make_coupon(self._coupon.stage, width=self.measured_width.value(),
                           pitch=self.tested_pitch.value(), rings=self.test_rings.value())
            job = self._make_job()
        except ValueError as e:
            return self._say(str(e), warn=True)
        directory = workspace.workspace_root() / "exports" / "copper-calibration"
        directory.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        gcode_path = directory / f"{run_id}.gcode"
        gcode_path.write_text(job.text, encoding="ascii", newline="")
        record = dict(id=run_id, sample=self._sample_id, material=self.material.text(),
                      stage=self._coupon.stage, cell=None if self._grid() else self._cell+1,
                      label="Exposure grid" if self._grid() else self._coupon.labels[self._cell],
                      coupon_mm=[cc.SIZE, cc.SIZE], measured_width_mm=self._coupon.width,
                      pitch_mm=self._coupon.pitch, rings=self._coupon.rings,
                      power_percent=self.power.value(),
                      speed_mm_s=None if self._grid() else self.speed.value(),
                      frequency_khz=self.freq.value(),
                      passes_requested=job.passes,
                      grid=([{"cell": i + 1, "speed_mm_s": v, "passes": n}
                             for i, (v, n) in enumerate(self._coupon.exposures)]
                            if self._grid() else None),
                      origin_mm=list(self.origin()), turns=self.turns, fine_degrees=self.fine,
                      camera_offset_mm=list(self.cam_offset),
                      geometry_key=self._geometry_key(), gcode_sha256=hashlib.sha256(job.text.encode("ascii")).hexdigest(),
                      gcode_path=str(gcode_path), record_path=str(directory / f"{run_id}.json"),
                      timestamp_utc=datetime.now(timezone.utc).isoformat(),
                      status="prepared", observation="Not inspected", notes="")
        self._write_record(record)
        self._records.append(record)
        self._pending_record = record
        self._latest = record
        self._stopped = False
        self._job = job
        self._zone_holes = [set(range(len(self._coupon.cells))) if self._grid() else {self._cell}]
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)
        take_photo = self.photo_after.isChecked()

        def work(progress):
            z = self.laser.z()
            record["head_z_mm"] = z
            record["status"] = "started"
            self._write_record(record)
            self.laser.run(job.text)
            self.laser.wait(max(120, job.seconds*2+30), progress=progress)
            record["status"] = "interrupted" if self._stopped else "completed"
            record["finished_utc"] = datetime.now(timezone.utc).isoformat()
            self._write_record(record)
            photo_error = ""
            rgb = None
            if take_photo and not self._stopped:
                try:
                    rgb = self._photo()
                except Exception as e:  # The pass completed even if the camera fails.
                    photo_error = str(e)
            return rgb, photo_error

        def done(result):
            rgb, error = result
            if rgb is not None:
                self.show_bed(rgb)
            self.result.setCurrentIndex(0)
            self.notes.clear()
            self._pending_record = None
            self._update_count()
            if self._stopped:
                return "Stopped. This attempt may be partial; use a fresh cell for a counted comparison."
            if self._grid():
                return ("Grid done. Look at it under a loupe: find the cell where the copper is "
                        "cleared all along the line with the fewest passes and no charring. "
                        "Record it, then switch to Single lines with that speed and passes."
                        + (f" Photo failed: {error}" if error else ""))
            return (f"Cell {record['cell']}: {job.passes} pass{'' if job.passes == 1 else 'es'} "
                    "completed. Cool, inspect and record the result."
                    + (f" Photo failed: {error}" if error else ""))
        what = ("the exposure grid" if self._grid()
                else f"ONLY cell {self._cell+1}, {job.passes} pass{'' if job.passes == 1 else 'es'}")
        self._start(work, f"Running {what}…", done)

    def _done(self, msg, warn):
        if warn and self._pending_record is not None:
            self._pending_record["status"] = "interrupted" if self._stopped else "failed_or_partial"
            self._pending_record["error"] = msg
            self._write_record(self._pending_record)
            self._pending_record = None
        super()._done(msg, warn)
        self._update_count()
        self._sync_run_ready()

    def _busy(self, on):
        self._calibration_running = on
        super()._busy(on)
        for control in getattr(self, "_coupon_controls", []):
            control.setEnabled(not on)
        if not on:
            self._sync_run_ready()

    def stop(self):
        self._stopped = True
        super().stop()

    def record_observation(self):
        if self._latest is None:
            return self._say("Run a calibration cell before recording its observation.", warn=True)
        self._latest["observation"] = self.result.currentText()
        self._latest["notes"] = self.notes.text()
        self._write_record(self._latest)
        self._say(f"Observation saved for {self._latest['stage']}, cell {self._latest['cell']}.")

    def new_sample(self):
        self._sample_id = uuid.uuid4().hex
        self._latest = None
        self.fresh_stage.setChecked(False)
        self.result.setCurrentIndex(0)
        self.notes.clear()
        self._update_count()
        self._say("New sample started. Counts now refer to this fresh piece of copper.")

    def save_measured_recipe(self):
        r = self._latest
        if r is None or r["stage"] != "Corners and pads" or r["status"] != "completed" or r["observation"] != "Clean isolation":
            return self._say("First record Clean isolation for a completed corners/pads test, "
                             "after checking resistance and laminate condition.", warn=True)
        group_fields = ("sample", "stage", "origin_mm", "turns", "fine_degrees",
                        "measured_width_mm", "pitch_mm", "rings")
        group = [p for p in self._records if all(p[f] == r[f] for f in group_fields)]
        latest_by_cell = {p["cell"]: p for p in group}
        if len(latest_by_cell) != 5 or any(p["status"] != "completed" or p["observation"] != "Clean isolation"
                                           for p in latest_by_cell.values()):
            return self._say("Record Clean isolation on all five corners/pads cells at the same "
                             "placement before saving a production recipe.", warn=True)
        attempts = group
        if any(p["status"] != "completed" for p in attempts):
            return self._say("This cell includes an interrupted/uncertain attempt. Qualify a fresh cell.", warn=True)
        fields = ("power_percent", "speed_mm_s", "frequency_khz")
        if any(any(p[f] != r[f] for f in fields) for p in attempts):
            return self._say("This cell used mixed exposures. Qualify a fresh cell at one exposure before saving.", warn=True)
        counts = {sum(p.get("passes_requested", 1) for p in attempts if p["cell"] == cell)
                  for cell in range(1, 6)}
        if len(counts) != 1:
            return self._say("The five cells were tested at different pass counts. A production recipe "
                             "needs one common pass count that clears all five without damage.", warn=True)
        pass_count = counts.pop()
        name, ok = QInputDialog.getText(self, "Save measured vector recipe", "Recipe name:",
                                        text="Measured FR4 vectors")
        if not ok or not name.strip():
            return
        recipe = xtool.TracesRecipe(power=r["power_percent"], speed=r["speed_mm_s"],
                                    frequency=r["frequency_khz"], passes=pass_count,
                                    kerf=r["measured_width_mm"], lines_per_cm=10/r["pitch_mm"],
                                    offsets=r["rings"], spot_drills=False, mark_outline=False)
        cfg = QSettings(*sl._SETTINGS)
        try:
            saved = json.loads(cfg.value("presets_traces", "{}"))
        except (ValueError, TypeError):
            saved = {}
        if name.strip() in sl.TRACES_PRESETS:
            return self._say("Choose a new name for the measured recipe.", warn=True)
        saved[name.strip()] = asdict(recipe)
        saved[name.strip()]["_calibration"] = {
            "qualifying_passes_with_manual_inspection": pass_count,
            "sample": r["sample"], "record": r["record_path"],
            "all_five_cells": True,
        }
        cfg.setValue("presets_traces", json.dumps(saved))
        cfg.sync()
        if cfg.status() != QSettings.NoError:
            return self._say("The measured recipe could not be saved to settings. "
                             "The experiment files are still in the export folder.", warn=True)
        self.saved_recipe_name = name.strip()
        self._say(f"Saved {name.strip()} with {pass_count} passes, the count that cleared all "
                  "five cells.")
