"""The PCB editor button: show how much of the SRM-20 this board can use.

A board that does not fit the machine is normally discovered at the machine,
after the layout is finished and the stock is cut. This puts the answer on
screen while there is still time to do something about it.
"""
import os

import pcbnew
import wx

from srm20area import draw
from srm20area import geometry as g

TITLE = "SRM-20 build area"


class SRM20BuildAreaAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "Show SRM-20 build area..."
        self.category = "Modify PCB"
        self.description = ("Draw the SRM-20's build area on User.Drawings and "
                            "say whether this board fits it.")
        self.show_toolbar_button = True
        icon = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon):
            self.icon_file_name = icon

    def Run(self):
        board = pcbnew.GetBoard()
        try:
            stats = draw.show(board)
        except Exception as exc:                       # noqa: BLE001
            import traceback
            wx.MessageBox("Could not draw the build area:\n\n%s\n\n%s"
                          % (exc, traceback.format_exc()),
                          TITLE, wx.OK | wx.ICON_ERROR)
            return

        pcbnew.Refresh()
        wx.MessageBox(draw.summary(stats) +
                      "\n\nNothing is saved yet — Ctrl+Z undoes it.",
                      TITLE, wx.OK | wx.ICON_INFORMATION)
