"""The mill's settings sheet (gui2/millsettings.py).

Opening it reads and changes nothing; each of the two changes is a button.
No real USB: the engine's functions are swapped for a small pretend mill,
and the sheet's exec() is replaced by whatever the test wants pressed."""
import pytest
from PySide6.QtWidgets import QPushButton, QSpinBox

from gerber2rml.engine import millsetup
from gerber2rml.gui2 import dialogs, millsettings


class Mill:
    def __init__(self, cset="nc", g54=(0.0, 0.0, -55.64), percent=100):
        self.cset, self.g54, self.percent = cset, g54, percent
        self.wrote = []


@pytest.fixture
def mill(monkeypatch, qt_app):
    m = Mill()
    monkeypatch.setattr(millsetup, "command_set", lambda d: d.cset)
    monkeypatch.setattr(millsetup, "g54_origin", lambda d: d.g54)
    monkeypatch.setattr(millsetup, "status",
                        lambda d: {"spindle_percent": d.percent})

    def set_cs(d, nc=True):
        d.wrote.append(("set", nc))
        d.cset = "nc" if nc else "rml"
        return d.cset

    def set_sp(d, percent):
        d.wrote.append(("spindle", percent))
        d.percent = percent
        return percent

    monkeypatch.setattr(millsetup, "set_command_set", set_cs)
    monkeypatch.setattr(millsetup, "set_spindle_percent", set_sp)
    return m


def press(monkeypatch, *labels, percent=None):
    """Make the sheet's exec() press these buttons, and note what it said."""
    seen = {}

    def run(sheet):
        if sheet.objectName() != "millSettingsSheet":
            return 1
        if percent is not None:
            sheet.findChild(QSpinBox, "spindlePercent").setValue(percent)
        buttons = {b.text(): b for b in sheet.findChildren(QPushButton)}
        seen["offers_nc"] = not buttons[
            "Set the command set to NC Code"].isHidden()
        for label in labels:
            buttons[label].click()
        seen["offers_nc_after"] = not buttons[
            "Set the command set to NC Code"].isHidden()
        return 1

    monkeypatch.setattr(dialogs.Sheet, "exec", run)
    return seen


def test_opening_the_sheet_changes_nothing(mill, monkeypatch):
    seen = press(monkeypatch)
    now = millsettings.settings_sheet(None, open_mill=lambda: mill)
    assert now["set"] == "nc" and mill.wrote == []
    assert seen["offers_nc"] is False


def test_a_mill_in_rml_is_offered_nc_and_set_on_the_button(mill, monkeypatch):
    mill.cset = "rml"
    seen = press(monkeypatch, "Set the command set to NC Code")
    now = millsettings.settings_sheet(None, open_mill=lambda: mill)
    assert seen["offers_nc"] is True and seen["offers_nc_after"] is False
    assert mill.wrote == [("set", True)] and now["set"] == "nc"


def test_the_spindle_speed_is_set_to_what_the_box_says(mill, monkeypatch):
    press(monkeypatch, "Set the spindle speed", percent=60)
    millsettings.settings_sheet(None, open_mill=lambda: mill)
    assert mill.wrote == [("spindle", 60)]


def test_a_mill_that_cannot_be_reached_is_explained(mill, monkeypatch):
    errors = []
    monkeypatch.setattr(dialogs, "report_error",
                        lambda *a, **k: errors.append(a[1]))

    def gone():
        raise millsetup.SetupError("no SRM-20 on USB")

    assert millsettings.settings_sheet(None, open_mill=gone) is None
    assert errors == ["The mill's settings could not be read"]


def test_a_change_the_mill_refuses_is_reported_and_nothing_is_claimed(
        mill, monkeypatch):
    mill.cset = "rml"
    errors = []
    monkeypatch.setattr(dialogs, "report_error",
                        lambda *a, **k: errors.append(a[1]))

    def refuse(d, nc=True):
        raise millsetup.SetupError("the mill is moving")

    monkeypatch.setattr(millsetup, "set_command_set", refuse)
    seen = press(monkeypatch, "Set the command set to NC Code")
    now = millsettings.settings_sheet(None, open_mill=lambda: mill)
    assert errors == ["The command set could not be changed"]
    assert now["set"] == "rml" and seen["offers_nc_after"] is True


def test_g54_at_machine_zero_is_fine_and_anything_else_is_said():
    assert millsettings.g54_note((0.0, 0.0, -55.64))[1] is True
    text, ok = millsettings.g54_note((12.5, 0.0, -55.64))
    assert ok is False and "frame check" in text and "12.50" in text


# --- before a run ----------------------------------------------------------

@pytest.fixture
def asked(monkeypatch):
    said = {"heads": [], "yes": True, "errors": []}
    monkeypatch.setattr(millsettings, "_ask",
                        lambda parent, head, text, go, level="warn":
                        said["heads"].append((head, go)) or said["yes"])
    monkeypatch.setattr(dialogs, "report_error",
                        lambda *a, **k: said["errors"].append(a[1]))
    return said


def test_a_mill_set_up_right_starts_without_a_word(mill, asked):
    assert millsettings.preflight(None, open_mill=lambda: mill) is True
    assert asked["heads"] == [] and mill.wrote == []


def test_a_mill_in_rml_is_set_to_nc_and_the_log_says_so(mill, asked):
    """No question - but never silently: the setting is shared."""
    mill.cset = "rml"
    log = []
    assert millsettings.preflight(None, open_mill=lambda: mill,
                                  say=lambda lv, t: log.append((lv, t))) is True
    assert asked["heads"] == [] and mill.wrote == [("set", True)]
    assert len(log) == 1 and log[0][0] == "warn"
    assert "RML-1" in log[0][1] and "NC Code" in log[0][1]


def test_a_mill_already_in_nc_puts_nothing_in_the_log(mill, asked):
    log = []
    millsettings.preflight(None, open_mill=lambda: mill,
                           say=lambda lv, t: log.append(t))
    assert log == []


def test_a_command_set_that_will_not_change_stops_the_run(
        mill, asked, monkeypatch):
    mill.cset = "rml"

    def refuse(d, nc=True):
        raise millsetup.SetupError("the mill still reads RML-1")

    monkeypatch.setattr(millsetup, "set_command_set", refuse)
    assert millsettings.preflight(None, open_mill=lambda: mill) is False
    assert asked["errors"] == [
        "The mill is set to RML-1 and could not be changed"]


def test_g54_off_zero_is_said_before_anything_is_probed(mill, asked):
    mill.g54 = (10.0, 0.0, -55.64)
    asked["yes"] = False
    assert millsettings.preflight(None, open_mill=lambda: mill) is False
    assert asked["heads"] == [("G54 is not at machine 0, 0", "Start anyway")]
    assert mill.wrote == []


def test_a_mill_that_cannot_be_read_leaves_the_choice_to_the_operator(
        mill, asked):
    def gone():
        raise millsetup.SetupError("no SRM-20 on USB")

    assert millsettings.preflight(None, open_mill=gone) is True
    assert asked["heads"] == [("The mill's settings could not be checked",
                               "Start anyway")]
    asked["yes"] = False
    assert millsettings.preflight(None, open_mill=gone) is False
