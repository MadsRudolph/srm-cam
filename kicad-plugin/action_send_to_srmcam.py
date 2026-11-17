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


def _guess_method(info):
    """The method to offer first when a board has none yet: the mill bit
    SRM-CAM has selected (the ball mill cuts a channel under 0.6 mm)."""
    return "mill_ball" if _cutter_mm(info) < 0.6 else "mill_flat"


def choose_rules(board, info):
    """Show the design-rules window, apply what is chosen, and say what
    changed. True when rules were applied."""
    from srm20area import methods, rules, rules_dialog
    board_file = board.GetFileName()
    stored, _ = methods.read_method(board_file) if board_file else (None, None)
    rules_path = rules.rules_file(board)
    rules_text = ""
    if rules_path:
        try:
            with open(rules_path, encoding="utf-8") as f:
                rules_text = f.read()
        except OSError:
            pass
    current = rules.read_current(board)
    picked = rules_dialog.ask(None, current, stored or _guess_method(info),
                              _drill_mm(info), rules_text)
    if picked is None:
        return False
    method_id, values = picked
    ops = methods.plan(current, values)
    wx.BeginBusyCursor()
    try:
        changed = rules.apply_plan(board, ops, values["drill"])
    finally:
        wx.EndBusyCursor()
    pcbnew.Refresh()
    remembered = ""
    if board_file:
        try:
            methods.write_method(board_file, method_id, values)
            remembered = ("\n\n*Send to SRM-CAM* now checks this board for "
                          "this method (kept in srm-cam/method.json).")
        except OSError:
            pass
    notes = methods.rule_file_notes(rules_text, values)
    wx.MessageBox(
        "%s:\n\n    %s%s\n\nThe pours are refilled. Tracks are where they "
        "were: run Inspect > Design Rules Checker and move what it marks. "
        "Save to keep the changes; close without saving to undo them.%s"
        % (methods.method(method_id)["name"],
           "\n    ".join(changed) or "nothing needed changing",
           ("\n\nThe custom rules file still decides some of this:\n    "
            + "\n    ".join(notes)) if notes else "",
           remembered),
        "Design rules for SRM-CAM", wx.OK | wx.ICON_INFORMATION)
    return True


def board_check(board, info):
    """``(problems, what they were checked against)`` before a send. A board
    with a method set is checked for that method; one without, for the mill
    bit SRM-CAM has selected, as before."""
    from srm20area import methods, rules
    board_file = board.GetFileName()
    method_id, values = methods.read_method(board_file) if board_file else (None, None)
    if method_id:
        want = methods.defaults(method_id, _drill_mm(info))
        want.update(values or {})
        return (methods.too_tight(rules.read_current(board), want),
                methods.method(method_id)["name"])
    cutter, drill = _cutter_mm(info), _drill_mm(info)
    found, _want = rules.too_tight(board, cutter, drill)
    return found, ("the SRM-20's %.2f mm cutter and %.2f mm drill"
                   % (cutter, drill))


class SRM20RulesAction(pcbnew.ActionPlugin):
    """Tools > External Plugins > Set design rules for SRM-CAM."""

    def defaults(self):
        self.name = "Set design rules for SRM-CAM"
        self.category = "Modify PCB"
        self.description = ("Choose how the board is made - flat endmill, "
                            "ball mill or fiber laser - and set the design "
                            "rules that method needs, before laying tracks.")
        self.show_toolbar_button = True
        icon = os.path.join(os.path.dirname(__file__), "icon_rules.png")
        if os.path.exists(icon):
            self.icon_file_name = icon

    def Run(self):
        board = pcbnew.GetBoard()
        info = sendto.read_launch_info(os.path.dirname(__file__))
        choose_rules(board, info)


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
        # Rules tighter than the board's method can make mean nets that are
        # not separated: better found here, where they can be fixed.
        try:
            found, against = board_check(board, info)
        except Exception:                               # noqa: BLE001
            found = []
        if found:
            ask = wx.MessageDialog(
                None,
                "This board asks for more than %s can make:\n\n    %s\n\n"
                "Open the design rules and set them for how the board is "
                "made? The board is not sent yet."
                % (against, "\n    ".join(found)),
                TITLE, wx.YES_NO | wx.CANCEL | wx.ICON_WARNING)
            ask.SetYesNoCancelLabels("Set the rules...", "Send anyway", "Cancel")
            answer = ask.ShowModal()
            ask.Destroy()
            if answer == wx.ID_YES:
                choose_rules(board, info)
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
