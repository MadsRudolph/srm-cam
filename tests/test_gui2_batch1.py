"""The first batch ported from the original interface: F1 to the web guide,
Pause / Resume on the bar, resuming a part-done probe grid, and rework
boxes surviving a setup save. Nothing here touches a serial port."""
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

from gerber2rml.gui2 import dialogs, leveling
from gerber2rml.gui2.window import MainWindow, USER_GUIDE_URL

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"


@pytest.fixture
def win(qt_app):
    w = MainWindow()
    w.resize(1400, 900)
    yield w
    w.close()


@pytest.fixture
def loaded(win):
    win.load_folder(str(FIXT))
    return win


# --- F1 --------------------------------------------------------------------

def test_f1_is_the_web_guide(win):
    assert win.guide_act.shortcut().toString() == "F1"
    assert USER_GUIDE_URL.startswith("https://madsrudolph.github.io/srm-cam")


# --- pause / resume ----------------------------------------------------------

class _Link:
    """The bar's view of a link, with a recorder instead of a port."""
    def __init__(self, connected=True):
        self.connected = connected
        self.calls = []
        self._paused = False

    def pause(self):
        if not self.connected:
            return False
        self.calls.append("pause"); self._paused = True
        return True

    def resume(self):
        if not self.connected:
            return False
        self.calls.append("resume"); self._paused = False
        return True

    def can_stop_something(self):
        return self.connected

    def stop_now(self):
        self.calls.append("stop"); self._paused = False


def test_the_pause_button_holds_and_resumes(win):
    link = _Link()
    win.bar.link = link
    win.bar.pause_btn.click()
    assert link.calls == ["pause"]
    assert win.bar.pause_btn.text() == "Resume"
    win.bar.pause_btn.click()
    assert link.calls == ["pause", "resume"]
    assert win.bar.pause_btn.text() == "Pause"


def test_stop_cancels_a_hold(win):
    """A stop is not a hold: after STOP nothing resumes, and the button must
    not claim otherwise."""
    link = _Link()
    win.bar.link = link
    win.bar.pause_btn.click()
    win.bar.stop_btn.click()
    assert link.calls == ["pause", "stop"]
    assert not win.bar.pause_btn.isChecked()
    assert win.bar.pause_btn.text() == "Pause"


def test_pause_without_a_link_says_so_and_stays_up(win):
    win.bar.link = _Link(connected=False)
    win.bar.pause_btn.click()
    assert not win.bar.pause_btn.isChecked()


def test_the_real_link_holds_a_stream_by_flag_and_a_file_by_command():
    """Streaming owns the port inside one long op, so it is held by the flag
    its loop polls; a VPanel job is held by the firmware's suspendJob, which
    goes through the queue like any command. STOP clears either."""
    from gerber2rml.gui2.machine import MachineLink
    link = MachineLink()
    assert not link.should_pause()
    # nothing connected: a hold has nothing to hold
    assert link.pause() is False
    link._ser = object()                         # "connected"
    link._current = "stream"
    assert link.pause() is True and link.should_pause()
    assert link._q.empty()                       # flag only, nothing queued
    link._current = None
    assert link.resume() is True and not link.should_pause()
    assert link._q.get_nowait()[0] == "resume"   # went through the queue
    link.pause()
    link._q.get_nowait()
    link._ser = None
    link.stop_now()
    assert not link.should_pause()


# --- resume probing -----------------------------------------------------------

def test_resume_selection_reprobes_the_anchor_and_only_the_gaps():
    assert leveling.resume_selection([True, True, False, True, False]) == [0, 2, 4]
    assert leveling.resume_selection([True, True, True]) == [0]
    assert leveling.resume_selection([]) == []


def test_a_part_done_grid_is_offered_to_resume(loaded, monkeypatch):
    """After a STOP, the measured points are kept and the run picks up the
    rest. The dialog has named buttons, because it sits directly in front
    of a probing run."""
    page = loaded.level_page
    page.nx.setValue(2); page.ny.setValue(2); page._build()
    from PySide6.QtWidgets import QTableWidgetItem
    page.table.setItem(0, 2, QTableWidgetItem("0.0000"))
    page.table.setItem(1, 2, QTableWidgetItem("0.0120"))
    assert page._measured() == [True, True, False, False]

    seen = []
    def fake_exec(self):
        seen.append({b.text() for b in self.findChildren(QPushButton)})
        return 0
    monkeypatch.setattr(dialogs.Sheet, "exec", fake_exec)
    assert page._ask_resume(2, 2) is None            # exec stub = Cancel
    assert seen and "Only the missing 2" in seen[0] and "Probe all again" in seen[0]


# --- rework boxes in the setup file --------------------------------------------

def test_rework_boxes_survive_a_setup_save_and_load(loaded, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    page = loaded.rework_page
    page.depth.setValue(0.4)
    page.add_region(10, 10, 20, 15)
    page.add_region(30, 5, 25, 9)                 # given backwards, stored sorted
    path = tmp_path / "job.srmcam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_save_setup()
    data = json.loads(path.read_text())
    assert data["rework"]["regions"] == [[10, 10, 20, 15, 0.4], [25, 5, 30, 9, 0.4]]

    page._clear()
    assert page._regions == []
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    loaded.action_load_setup()
    assert loaded.rework_page._regions == [(10, 10, 20, 15, 0.4), (25, 5, 30, 9, 0.4)]
    assert loaded.rework_page.table.rowCount() == 2
