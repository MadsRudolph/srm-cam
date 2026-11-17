"""The xTool F1 Ultra laser page on its own, without SRM-CAM's milling steps.

    srm-cam-laser                      the last Gerber folder, or the page empty
    srm-cam-laser <gerber-folder>      that board: traces, mask, silkscreen, stencil
    srm-cam-laser <board.dxf>          copper traces from a DXF drawing
    srm-cam-laser --job mask <folder>  open on that job
    srm-cam-laser --calibrate          the copper calibration window

It builds the jobs the way the main window does for a single-sided board: the
bottom face mirrored like the milled copper, and the top face as plotted when
the bottom has nothing on it.
"""
import argparse
import sys
from pathlib import Path

_SETTINGS = ("SRM-CAM", "laser-app")
KINDS = ("traces", "mask", "silk", "stencil")


def job_builder(folder):
    """``jobs(kind, side=None)`` -> :class:`xtool.LaserArt` for ``folder``,
    as the laser page's job switch asks for it."""
    from gerber2rml.engine import silkscreen, soldermask, stencil, xtool
    from gerber2rml.loader import _find_layer
    folder = Path(folder)

    def raw_outline():
        edge = _find_layer(folder, "*-Edge_Cuts.*", "*.gm1")
        return soldermask._read_outline(edge) if edge else None

    def features(mirror):
        try:
            return xtool.drill_features(folder, mirror, raw_outline())
        except Exception:                       # noqa: BLE001 - Align only
            return []

    def jobs(kind, *, side=None):
        if kind == "traces":
            if side is not None:
                return xtool.build_laser_traces(folder, side=side,
                                                mirror=side == "bottom")
            # The face with the most copper: a fab-made board like curtain-drive
            # has a handful of pads on B.Cu and every trace on F.Cu.
            faces = []
            for face, mirror in (("bottom", True), ("top", False)):
                try:
                    art = xtool.build_laser_traces(folder, side=face, mirror=mirror)
                except xtool.TracesError:
                    continue
                faces.append((getattr(art.copper, "area", 0.0), face == "bottom", art))
            if not faces:
                raise xtool.TracesError(f"No copper Gerber in {folder}.")
            return max(faces, key=lambda t: (t[0], t[1]))[2]
        if kind == "mask":
            art = soldermask.build_mask(folder, mirror=True)
            return xtool.LaserArt(kind="mask", apertures=art.openings,
                                  outline=art.outline, mirrored=art.mirrored,
                                  notes=art.warnings(), features=features(True),
                                  note=f"shrunk {art.shrink:g} mm a side")
        if kind == "silk":
            art = silkscreen.build_silk(folder)
            return xtool.LaserArt(kind="silk", apertures=art.shapes,
                                  outline=art.outline, mirrored=art.mirrored,
                                  notes=art.warnings(), features=features(art.mirrored))
        if kind == "stencil":
            try:
                return stencil.build_stencil(folder, side="bottom")
            except stencil.StencilError:
                return stencil.build_stencil(folder, side="top", mirror=False)
        raise ValueError(f"Unknown laser job: {kind}")
    return jobs


def first_job(folder, prefer=None):
    """The first job ``folder`` can give, ``prefer`` first. (kind, art)."""
    jobs = job_builder(folder)
    order = ([prefer] if prefer else []) + [k for k in KINDS if k != prefer]
    last = None
    for kind in order:
        try:
            return kind, jobs(kind)
        except Exception as e:                  # noqa: BLE001 - try the next job
            last = e
    raise ValueError(f"No laser job in {folder}: {last}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="srm-cam-laser", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path,
                    help="a Gerber folder, or a .dxf of the copper")
    ap.add_argument("--job", choices=KINDS)
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args(argv)

    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
    from gerber2rml import glconfig
    from gerber2rml.gui2 import style, theme

    if QApplication.instance() is None:
        glconfig.configure()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SRM-CAM")
    app.setOrganizationName("SRM-CAM")
    base = QFont(theme.BODY_FAMILY[0])
    base.setFamilies(theme.BODY_FAMILY)
    base.setPointSizeF(theme.SIZE_BODY * 0.75)
    app.setFont(base)
    app.setStyleSheet(style.STYLESHEET)

    if a.calibrate:
        from gerber2rml.gui2.copper_calibration import CopperCalibrationDialog
        CopperCalibrationDialog().exec()
        return 0

    if a.folder is not None and a.folder.suffix.lower() == ".dxf":
        from gerber2rml.engine import dxf_traces, xtool
        from gerber2rml.gui2.stencil_laser import StencilLaserDialog
        try:
            art = dxf_traces.build_dxf_traces(a.folder)
        except xtool.TracesError as e:
            QMessageBox.warning(None, "SRM-CAM laser", str(e))
            return 1
        StencilLaserDialog(art, None, name=a.folder.name, dxf=a.folder).exec()
        return 0

    cfg = QSettings(*_SETTINGS)
    folder = a.folder
    if folder is None:
        last = cfg.value("folder", "")
        folder = Path(last) if last and Path(last).is_dir() else None
    if folder is None:
        # Nothing to open: the page on its own, to load a folder or a DXF
        # there or to calibrate.
        from gerber2rml.gui2.stencil_laser import StencilLaserDialog
        StencilLaserDialog(None, None).exec()
        return 0
    try:
        kind, art = first_job(folder, a.job)
    except ValueError as e:
        QMessageBox.warning(None, "SRM-CAM laser", str(e))
        return 1
    cfg.setValue("folder", str(folder))

    from gerber2rml.gui2.stencil_laser import StencilLaserDialog
    d = StencilLaserDialog(art, None, name=folder.name, jobs=job_builder(folder))
    d.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
