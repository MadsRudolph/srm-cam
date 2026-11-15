"""Plot the open board from inside KiCad, for SRM-CAM.

The plot controller and the Excellon writer, in the PCB editor's own
process: the board as it is on screen, unsaved edits included, and no
``kicad-cli`` process - on a Mac every one of those showed up in the Dock as
another KiCad. The controller keeps its own plot settings, so the board's
(File > Plot) are not changed.

The files are named as ``kicad-cli`` names them, which is what SRM-CAM's
loader looks for. :mod:`sendto` falls back to ``kicad-cli`` when this KiCad's
scripting API does not match.
"""
import os

import pcbnew

from srm20area import sendto

# (layer, file suffix) - the suffix is KiCad's own layer name with "_".
LAYERS = [(pcbnew.F_Cu, "F_Cu"), (pcbnew.B_Cu, "B_Cu"),
          (pcbnew.Edge_Cuts, "Edge_Cuts"),
          (pcbnew.F_Mask, "F_Mask"), (pcbnew.B_Mask, "B_Mask"),
          (pcbnew.F_SilkS, "F_Silkscreen"), (pcbnew.B_SilkS, "B_Silkscreen")]


def _no_drill_marks():
    for name in ("DRILL_MARKS_NO_DRILL_SHAPE", "NO_DRILL_SHAPE"):
        if hasattr(pcbnew, name):
            return getattr(pcbnew, name)
        if hasattr(pcbnew.PCB_PLOT_PARAMS, name):
            return getattr(pcbnew.PCB_PLOT_PARAMS, name)
    return 0


def plot(board, out_dir):
    """Gerbers and PTH/NPTH Excellon for ``board`` into ``out_dir``."""
    out_dir = sendto.clear_plotted(out_dir)
    pc = pcbnew.PLOT_CONTROLLER(board)
    po = pc.GetPlotOptions()
    po.SetOutputDirectory(out_dir)
    po.SetFormat(pcbnew.PLOT_FORMAT_GERBER)
    po.SetUseGerberProtelExtensions(True)
    po.SetPlotFrameRef(False)
    po.SetUseAuxOrigin(False)
    po.SetSubtractMaskFromSilk(False)
    po.SetMirror(False)
    po.SetNegative(False)
    po.SetScale(1)
    po.SetDrillMarksType(_no_drill_marks())
    try:
        for layer, suffix in LAYERS:
            pc.SetLayer(layer)
            pc.OpenPlotfile(suffix, pcbnew.PLOT_FORMAT_GERBER, suffix)
            pc.PlotLayer()
    finally:
        pc.ClosePlot()

    drill = pcbnew.EXCELLON_WRITER(board)
    drill.SetOptions(False, False, pcbnew.VECTOR2I(0, 0), False)
    drill.SetFormat(True)                       # metric
    drill.CreateDrillandMapFilesSet(out_dir, True, False)
    sendto.check_plotted(out_dir)
    return out_dir
