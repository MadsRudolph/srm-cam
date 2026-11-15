"""Cut the board's solder paste stencil on the xTool F1 Ultra, from SRM-CAM.

The laser is plugged into this PC by USB. XCS still does the two things it is
good at, the camera and the autofocus: import the stencil DXF there, put it on
the foil in the camera image, autofocus, and read off X, Y and the thickness.
This window takes those three numbers and runs the cut, with the heat spread
over zones and rests that XCS cannot do (``engine/xtool.py``).

The laser calls block for seconds to minutes, so they run on a worker thread;
the window only shows what it reports and can always send Stop.
"""
from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QHBoxLayout, QProgressBar,
                               QSpinBox, QVBoxLayout, QWidget)

from gerber2rml.engine import xtool
from gerber2rml.gui2 import theme, widgets

_SETTINGS = ("SRM-CAM", "stencil-laser")


class _Worker(QThread):
    """Runs one laser action off the GUI thread."""

    progress = Signal(float)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self._fn(self.progress.emit) or "Done.")
        except Exception as e:              # noqa: BLE001 - shown to the operator
            self.failed.emit(str(e))


def _spin(value, lo, hi, step, decimals=2, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setKeyboardTracking(False)
    s.setSuffix(suffix)
    return s


def _ispin(value, lo, hi):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class StencilLaserDialog(QDialog):
    """``art`` is a :class:`gerber2rml.engine.stencil.StencilArtwork`."""

    def __init__(self, art, parent=None, laser=None):
        super().__init__(parent)
        self.art = art
        self.laser = laser or xtool.F1Ultra()
        self._worker = None
        self.setWindowTitle("Cut the stencil on the xTool F1 Ultra")
        self.setMinimumWidth(520)
        cfg = QSettings(*_SETTINGS)
        r = xtool.DEFAULT_RECIPE

        v = QVBoxLayout(self)
        v.setSpacing(theme.GAP_S)
        w, h = art.size
        v.addWidget(widgets.head(
            f"{len(art.apertures)} holes · {w:.1f} × {h:.1f} mm · "
            f"{'mirrored' if art.mirrored else 'not mirrored'} · "
            f"kerf {art.kerf:g} mm"))
        for msg in art.warnings():
            n = widgets.hint(msg)
            n.setStyleSheet(f"color: {theme.CAUTION};")
            v.addWidget(n)
        v.addWidget(widgets.hint(
            "In XCS: import the stencil DXF, drag it onto the foil in the camera "
            "image, and autofocus on the foil. Then copy its X, Y and the "
            "thickness here. X and Y are the top-left corner of the outline."))

        self.x = _spin(float(cfg.value("x", 67.0)), 0, xtool.BED_MM, 0.1)
        self.y = _spin(float(cfg.value("y", 67.0)), 0, xtool.BED_MM, 0.1)
        self.thickness = _spin(float(cfg.value("thickness", 4.1)), 0, 60, 0.1)
        v.addWidget(widgets.Field("X", self.x))
        v.addWidget(widgets.Field("Y", self.y))
        v.addWidget(widgets.Field(
            "Thickness", self.thickness,
            help="What XCS's autofocus reports for the foil on its carrier. The "
                 "head goes to this + 8 mm, the way XCS does it."))

        self.passes = _ispin(r.total_passes, 1, 200)
        self.burst = _ispin(r.passes_per_burst, 1, 50)
        self.rest = _spin(r.rest_s, 0, 120, 1, 0, " s")
        self.zones = _ispin(r.zones, 1, 12)
        more = widgets.Disclosure("Recipe", key="stencil-recipe")
        mv = more.body
        mv.addWidget(widgets.Field("Passes", self.passes,
                                   help="In total, per hole. 30 cuts 0.1 mm 304 "
                                        "stainless on the lab's F1 Ultra."))
        mv.addWidget(widgets.Field("Per burst", self.burst))
        mv.addWidget(widgets.Field("Rest", self.rest,
                                   help="Laser off after every burst. Each zone "
                                        "rests while the others are cut."))
        mv.addWidget(widgets.Field("Zones", self.zones))
        v.addWidget(more)

        self.status = widgets.body("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        v.addWidget(self.status)
        v.addWidget(self.bar)

        row = QWidget()
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        self.check_btn = widgets.button("Check the laser", on=self.check)
        self.trace_btn = widgets.button(
            "Show where", on=self.trace,
            tip="Runs the blue laser round the outline, faint enough not to "
                "mark steel, so you can see where the stencil will be cut.")
        self.cut_btn = widgets.button("Cut", kind="primary", on=self.cut)
        self.stop_btn = widgets.button("Stop", kind="stop", on=self.stop)
        for b in (self.check_btn, self.trace_btn, self.cut_btn, self.stop_btn):
            hb.addWidget(b)
        v.addWidget(row)
        self._busy(False)

    # -- the numbers -----------------------------------------------------
    def recipe(self):
        return xtool.Recipe(total_passes=self.passes.value(),
                            passes_per_burst=self.burst.value(),
                            rest_s=self.rest.value(), zones=self.zones.value())

    def paths(self):
        return xtool.stencil_paths(self.art, (self.x.value(), self.y.value()))

    def _remember(self):
        cfg = QSettings(*_SETTINGS)
        cfg.setValue("x", self.x.value())
        cfg.setValue("y", self.y.value())
        cfg.setValue("thickness", self.thickness.value())

    # -- actions ---------------------------------------------------------
    def check(self):
        def work(_p):
            info = self.laser.info()
            return (f"Connected: {info.get('deviceName', 'xTool')}, "
                    f"focus Z {self.laser.z():.2f}, {self.laser.mode()}.")
        self._start(work, "Asking the laser…")

    def trace(self):
        try:
            _, outline = self.paths()
            text = xtool.trace_job(outline)
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()

        def work(_p):
            self.laser.run(text)
            self.laser.wait(180)
            return "Traced. Move X/Y if it was not where the foil is."
        self._start(work, "Tracing the outline in blue…")

    def cut(self):
        try:
            holes, outline = self.paths()
            job = xtool.stencil_job(holes, outline, self.recipe())
        except ValueError as e:
            return self._say(str(e), warn=True)
        self._remember()
        t = self.thickness.value()
        self.bar.setRange(0, max(1, int(job.seconds)))
        self.bar.setValue(0)
        self.bar.setVisible(True)

        def work(progress):
            z = self.laser.focus(t)
            self.laser.run(job.text)
            self.laser.wait(job.seconds * 2 + 120, progress=progress)
            return (f"Cut: {sum(job.zones)} holes, {job.passes} passes, focus Z "
                    f"{z:.2f}. Push out any slugs before you check it.")
        self._start(work, f"Cutting, about {job.seconds / 60:.0f} min "
                          f"({len(job.zones)} zones)…")

    def stop(self):
        try:
            self.laser.stop()
            self._say("Stopped.")
        except xtool.LaserError as e:
            self._say(str(e), warn=True)

    # -- plumbing --------------------------------------------------------
    def _start(self, fn, text):
        self._say(text)
        self._busy(True)
        self._worker = _Worker(fn, self)
        self._worker.progress.connect(lambda s: self.bar.setValue(int(s)))
        self._worker.finished_ok.connect(lambda m: self._done(m, False))
        self._worker.failed.connect(lambda m: self._done(m, True))
        self._worker.start()

    def _done(self, msg, warn):
        self._busy(False)
        self.bar.setVisible(False)
        self._say(msg, warn=warn)

    def _busy(self, on):
        for b in (self.check_btn, self.trace_btn, self.cut_btn):
            b.setEnabled(not on)
        self.stop_btn.setEnabled(True)

    def _say(self, text, warn=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.CAUTION};" if warn else "")

    def closeEvent(self, e):
        if self._worker is not None and self._worker.isRunning():
            self._say("The laser is still running: press Stop first.", warn=True)
            e.ignore()
            return
        super().closeEvent(e)
