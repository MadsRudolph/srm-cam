"""The window behind *Set design rules for SRM-CAM*: pick how the board is made.

One choice - flat endmill, ball mill or fiber laser - fills in the numbers
that method has been cut with (methods.py). Every number can be changed
before it is applied; the board's own values are shown beside them, so it is
plain what will move. Meant for before the first track, and safe after: the
routing is never touched.
"""
import wx

from srm20area import methods


WRAP = 460      # px: the width the explanations are wrapped to


class RulesDialog(wx.Dialog):
    def __init__(self, parent, now, method_id, drill_mm, rules_text=""):
        wx.Dialog.__init__(self, parent, title="Design rules for SRM-CAM",
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._drill = drill_mm
        self._rules_text = rules_text or ""
        self._ids = [m["id"] for m in methods.METHODS]
        pad = 8
        top = wx.BoxSizer(wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="How is this board made?"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, pad)
        self.choice = wx.Choice(self, choices=[m["name"] for m in methods.METHODS])
        row.Add(self.choice, 1, wx.EXPAND)
        top.Add(row, 0, wx.EXPAND | wx.ALL, pad)

        self.about = wx.StaticText(self, label="")
        top.Add(self.about, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, pad)

        grid = wx.FlexGridSizer(cols=3, vgap=4, hgap=12)
        grid.AddGrowableCol(0)
        for text in ("", "Board now", "Set to (mm)"):
            label = wx.StaticText(self, label=text)
            label.SetFont(label.GetFont().Bold())
            grid.Add(label)
        self.spins = {}
        for key, text in methods.FIELDS:
            grid.Add(wx.StaticText(self, label=text), 0, wx.ALIGN_CENTER_VERTICAL)
            value = now.get(key)
            grid.Add(wx.StaticText(self, label="-" if value is None
                                   else "%.2f" % value), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
            spin = wx.SpinCtrlDouble(self, min=0.05, max=5.0, inc=0.05,
                                     size=(130, -1))
            spin.SetDigits(2)
            spin.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_value)
            spin.Bind(wx.EVT_TEXT, self._on_value)
            self.spins[key] = spin
            grid.Add(spin)
        top.Add(grid, 0, wx.EXPAND | wx.ALL, pad)

        self.notes = wx.StaticText(self, label="")
        self.notes.SetForegroundColour(wx.Colour(170, 80, 0))
        top.Add(self.notes, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, pad)

        foot = wx.StaticText(self, label=(
            "Sets the net classes, the board's minimums, every pour and the "
            "defaults for new pours, then refills the pours. Tracks are not "
            "moved: run DRC afterwards. Save to keep, or close without "
            "saving to undo."))
        top.Add(foot, 0, wx.EXPAND | wx.ALL, pad)

        buttons = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, "Apply")
        ok.SetDefault()
        buttons.AddButton(ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL))
        buttons.Realize()
        top.Add(buttons, 0, wx.EXPAND | wx.ALL, pad)

        self.choice.Bind(wx.EVT_CHOICE, self._on_method)
        foot.Wrap(WRAP)
        self.SetSizer(top)
        self.choice.SetSelection(self._ids.index(method_id)
                                 if method_id in self._ids else 0)
        self._on_method(None)

    # ------------------------------------------------------------- events
    def _on_method(self, _event):
        m = methods.METHODS[self.choice.GetSelection()]
        self.about.SetLabel(m["about"])
        self.about.Wrap(WRAP)
        for key, value in methods.defaults(m["id"], self._drill).items():
            self.spins[key].SetValue(value)
        self._on_value(None)

    def _on_value(self, event):
        if event is not None:
            event.Skip()
        v = self.values()
        notes = []
        if v["pour_gap"] < v["clearance"] - 0.0005:
            notes.append("KiCad keeps a pour at least the net-class clearance "
                         "(%.2f mm) from other copper, so it will not come to "
                         "%.2f mm." % (v["clearance"], v["pour_gap"]))
        if v["clearance"] < v["floor"] - 0.0005:
            notes.append("The clearance is under the board minimum; DRC will "
                         "use the minimum.")
        notes += methods.rule_file_notes(self._rules_text, v)
        if notes and self._rules_text:
            notes.append("Custom rules are under Board Setup > Design Rules > "
                         "Custom Rules. After editing them, run DRC once so "
                         "KiCad reads them again, then refill (B).")
        self.notes.SetLabel("\n".join(notes))
        self.notes.Wrap(WRAP)
        self.GetSizer().Fit(self)
        self.Layout()

    # -------------------------------------------------------------- result
    def method_id(self):
        return self._ids[self.choice.GetSelection()]

    def values(self):
        return {key: round(spin.GetValue(), 3) for key, spin in self.spins.items()}


def now_values(current):
    """The board's present numbers, one per field of the window."""
    default = current.get("classes", {}).get("Default", {})
    zones = current.get("zones") or []
    pour = zones[0] if zones else (current.get("zone_defaults") or {})
    b = current.get("board", {})
    return {"track": default.get("track"), "clearance": default.get("clearance"),
            "floor": b.get("floor"), "pour_gap": pour.get("clearance"),
            "thermal_gap": pour.get("thermal_gap"),
            "pour_min": pour.get("pour_min"), "edge": b.get("edge"),
            "drill": b.get("drill")}


def ask(parent, current, method_id, drill_mm, rules_text=""):
    """Show the window. ``(method id, values)`` on Apply, else None."""
    dlg = RulesDialog(parent, now_values(current), method_id, drill_mm, rules_text)
    try:
        if dlg.ShowModal() != wx.ID_OK:
            return None
        return dlg.method_id(), dlg.values()
    finally:
        dlg.Destroy()
