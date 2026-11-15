"""The PCB editor button: plot this board and open it in SRM-CAM.

One click instead of Plot, Generate Drill Files, switching to SRM-CAM and
File ▸ Open: every hand step is a chance to plot the wrong layers or open
yesterday's folder. The board is plotted as it is on screen, unsaved edits
included; the board file and its own plot settings are not touched.

The plot is made inside KiCad (srm20area/plot.py). Only if that fails - a
KiCad whose scripting API differs - is ``kicad-cli`` run on a copy of the
board instead.
"""
import os
import shutil
import tempfile

import pcbnew
import wx

from srm20area import sendto

TITLE = "Send to SRM-CAM"


def _save_copy(board, path):
    """Save the board as it is on screen to ``path``, without making that
    the project's location. False when this KiCad cannot (it would then
    move the project's settings with it)."""
    name = board.GetFileName()
    try:
        ok = pcbnew.SaveBoard(path, board, True)    # True: skip settings
    except TypeError:
        return False
    finally:
        if board.GetFileName() != name:
            board.SetFileName(name)
    return bool(ok)


def _plot_with_cli(board, board_file, out_dir):
    """The fallback: ``kicad-cli`` on a copy. Returns (folder, note)."""
    cli = sendto.find_kicad_cli()
    if cli is None:
        raise sendto.SendError("kicad-cli was not found next to this KiCad. "
                               "It ships with KiCad 7 and newer.")
    note = ""
    tmp = tempfile.mkdtemp(prefix="srm-cam-")
    try:
        copy = sendto.board_copy_path(tmp, board_file)
        if _save_copy(board, copy):
            sendto.copy_project_file(board_file, copy)
        else:
            copy = board_file
            note = ("This KiCad could not plot the board as it is on "
                    "screen, so the SAVED file was sent. Save (Ctrl+S) "
                    "and send again if you have changes.")
        return sendto.export(copy, out_dir, cli), note
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _mm(info, key, default):
    try:
        return float(info.get(key) or default)
    except (TypeError, ValueError):
        return default


def _cutter_mm(info):
    from srm20area import rules
    return _mm(info, "cutter_mm", rules.DEFAULT_CUTTER_MM)


def _drill_mm(info):
    from srm20area import rules
    return _mm(info, "drill_mm", rules.DEFAULT_DRILL_MM)


def _set_rules(board, cutter, drill):
    """Set the design rules and say what changed."""
    from srm20area import rules
    wx.BeginBusyCursor()
    try:
        changed = rules.apply(board, cutter, drill)
    finally:
        wx.EndBusyCursor()
    pcbnew.Refresh()
    wx.MessageBox(
        "Design rules set for a %.2f mm cutter and a %.2f mm drill:\n\n"
        "    %s\n\n"
        "The zones are refilled. The tracks are where they were: run "
        "Inspect > Design Rules Checker and move what it marks, then send "
        "the board. Save to keep the changes; close without saving to undo "
        "them."
        % (cutter, drill, "\n    ".join(changed) or "nothing needed changing"),
        "SRM-20 design rules", wx.OK | wx.ICON_INFORMATION)


class SRM20RulesAction(pcbnew.ActionPlugin):
    """Tools > External Plugins > Set SRM-20 design rules."""

    def defaults(self):
        self.name = "Set SRM-20 design rules"
        self.category = "Modify PCB"
        self.description = ("Set the clearance of the board, its net classes "
                            "and its zones to the SRM-20's cutter, so what "
                            "DRC passes the mill can cut.")
        self.show_toolbar_button = False

    def Run(self):
        from srm20area import rules
        board = pcbnew.GetBoard()
        info = sendto.read_launch_info(os.path.dirname(__file__))
        cutter, drill = _cutter_mm(info), _drill_mm(info)
        found, want = rules.too_tight(board, cutter, drill)
        if not found:
            wx.MessageBox("The design rules already suit a %.2f mm cutter and "
                          "a %.2f mm drill: every clearance is at least "
                          "%.2f mm and no via hole is smaller than the drill."
                          % (cutter, drill, want), "SRM-20 design rules",
                          wx.OK | wx.ICON_INFORMATION)
            return
        _set_rules(board, cutter, drill)


class SendToSRMCAMAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Send to SRM-CAM"
        self.category = "Fabrication outputs"
        self.description = ("Plot this board for the SRM-20 and open it in "
                            "SRM-CAM.")
        self.show_toolbar_button = True
        icon = os.path.join(os.path.dirname(__file__), "icon_send.png")
        if os.path.exists(icon):
            self.icon_file_name = icon

    def Run(self):
        board = pcbnew.GetBoard()
        board_file = board.GetFileName()
        if not board_file:
            wx.MessageBox("Save the board once first, so SRM-CAM has a name "
                          "and a folder for the files.", TITLE,
                          wx.OK | wx.ICON_INFORMATION)
            return
        info = sendto.read_launch_info(os.path.dirname(__file__))
        # Rules tighter than the cutter mean nets the mill cannot separate:
        # better found here, where they can be fixed, than in SRM-CAM.
        try:
            from srm20area import rules
            cutter, drill = _cutter_mm(info), _drill_mm(info)
            found, want = rules.too_tight(board, cutter, drill)
        except Exception:                               # noqa: BLE001
            found = []
        if found:
            ask = wx.MessageDialog(
                None,
                "This board asks for more than the SRM-20's %.2f mm cutter "
                "and %.2f mm drill can do:\n\n    %s\n\n"
                "Set the clearances to %.2f mm and the via holes to %.2f mm "
                "now? The board is not sent yet: run DRC afterwards and move "
                "what it marks."
                % (cutter, drill, "\n    ".join(found), want, drill),
                TITLE, wx.YES_NO | wx.CANCEL | wx.ICON_WARNING)
            ask.SetYesNoCancelLabels("Set the rules", "Send anyway", "Cancel")
            answer = ask.ShowModal()
            ask.Destroy()
            if answer == wx.ID_YES:
                _set_rules(board, cutter, drill)
                return
            if answer != wx.ID_NO:
                return
        out_dir = sendto.output_dir(board_file)
        note = ""
        wx.BeginBusyCursor()
        try:
            try:
                from srm20area import plot
                out = plot.plot(board, out_dir)
            except Exception:                           # noqa: BLE001
                out, note = _plot_with_cli(board, board_file, out_dir)
        except Exception as exc:                        # noqa: BLE001
            wx.EndBusyCursor()
            wx.MessageBox("The board could not be plotted:\n\n%s" % exc,
                          TITLE, wx.OK | wx.ICON_ERROR)
            return
        wx.EndBusyCursor()

        result = sendto.open_in_srmcam(out, info)
        if result == "busy":
            wx.MessageBox("SRM-CAM is running a job, so the board was not "
                          "loaded. The files are in:\n\n%s" % out, TITLE,
                          wx.OK | wx.ICON_WARNING)
        elif result == "missing":
            wx.MessageBox("SRM-CAM was not found. Open SRM-CAM once and use "
                          "KiCad ▸ Set up the build-area plugin… so this "
                          "button knows where it is. The files are in:\n\n%s"
                          % out, TITLE, wx.OK | wx.ICON_WARNING)
        elif note:
            wx.MessageBox(note, TITLE, wx.OK | wx.ICON_INFORMATION)
