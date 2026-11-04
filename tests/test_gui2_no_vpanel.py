"""What the window does on a system with the link and no VPanel: Linux, macOS.

The conftest pins every test to the CNC PC, so these set the capabilities
themselves, and the last few read the host's own. A real run goes to the
simulator, through the same runner the automatic run uses; nothing here opens a
serial port or a printer node.
"""
import re
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

from gerber2rml import platform as plat
from gerber2rml.engine import rmlspool
from gerber2rml.engine import simmachine as sm
from gerber2rml.gui2 import dialogs, machine, runplan
from gerber2rml.gui2.window import MainWindow

FIXT = Path(__file__).parent / "fixtures" / "mosfet_test"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_vpanel(monkeypatch):
    monkeypatch.setattr(plat, "capabilities", lambda p=None: plat.Capabilities(
        machine_link=True, job_routes=(plat.JOB_USBLP, plat.JOB_CUPS),
        vpanel=False, link_proven=False))


def _says(win):
    said = []
    win.say = lambda level, text: said.append((level, text))
    return said


@pytest.fixture
def win(qt_app, no_vpanel, monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    monkeypatch.setenv("SRM_CAM_MODE", "pro")
    sm.machine(speedup=1e6, corner=(41300, 27800), angle_deg=0.0,
               size=(150000, 120000))
    w = MainWindow()
    w.resize(1400, 900)
    w.load_folder(str(FIXT))
    yield w
    w.link.disconnect_from("test")
    if w.link._thread is not None:
        w.link._q.put(None)
        w.link._thread.join(2)
    w.close()


def _wait(qt_app, cond, secs):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < secs:
        qt_app.processEvents()
        time.sleep(0.01)
    return cond()


def _pick_step(w):
    step = next(s for s in w.plan.steps if s.kind == "run" and s.op == "airpass")
    w.select_step(step.key)
    return step


def _answer(monkeypatch, *, go=True, dry=True):
    got = {}

    def dialog(parent, title, moves, z):
        got.update(title=title, moves=moves, z=z)
        return {"go": go, "dry": dry}
    monkeypatch.setattr(dialogs, "run_step_dialog", dialog)
    return got


# ------------------------------------------------------------- the machine bar
def test_the_bar_lists_real_ports_and_says_how_jobs_run_here(qt_app, no_vpanel,
                                                             monkeypatch):
    class _Port:
        device, hwid = "/dev/ttyACM0", "USB VID:PID=2341:0043 SER=1"
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [_Port()])
    bar = machine.MachineBar(machine.MachineLink())
    assert not bar.sim_only
    assert bar.port_combo.itemData(0) == "/dev/ttyACM0"
    assert "Arduino" in bar.port_combo.itemText(0)
    assert "VPanel" in bar.offline_note.text()
    assert "no" in bar.offline_note.text().lower()
    bar.close()


def test_motherboard_serial_ports_are_not_in_the_list(qt_app, no_vpanel,
                                                      monkeypatch):
    """Seen in the built AppImage: 32 of them, ttyS31 first, and Connect lit,
    with nothing plugged in at all. pyserial 3.5's own filter no longer catches
    them on a current kernel."""
    if not sys.platform.startswith("linux"):
        pytest.skip("the filter reads the real platform")

    class _Ghost:
        device, hwid = "/dev/ttyS31", "n/a"

    class _Uno:
        device, hwid = "/dev/ttyACM0", "USB VID:PID=2341:0043"
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [_Ghost(), _Uno()])
    assert [d for d, _w in machine.list_ports()[0]] == ["/dev/ttyACM0"]
    monkeypatch.setattr(lp, "comports", lambda: [_Ghost()])
    ports, why = machine.list_ports()
    assert ports == [] and "no serial ports" in why


def test_real_ports_are_opened_here(qt_app, no_vpanel, monkeypatch):
    class _Port:
        device, hwid = "/dev/ttyUSB0", "USB VID:PID=1A86:7523"
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [_Port()])
    bar = machine.MachineBar(machine.MachineLink())
    opened = []
    monkeypatch.setattr(bar.link, "connect_to", opened.append)
    bar._toggle_connect()
    assert opened == ["/dev/ttyUSB0"]
    bar.close()


def test_no_ports_does_not_tell_you_to_send_from_vpanel(qt_app, no_vpanel,
                                                        monkeypatch):
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [])
    bar = machine.MachineBar(machine.MachineLink())
    assert "no serial ports" in bar.offline_note.text()
    assert "send them from VPanel" not in bar.offline_note.text()
    assert not bar.connect_btn.isEnabled()
    bar.close()


def test_plugging_in_and_rescanning_clears_the_no_ports_reason(qt_app, no_vpanel,
                                                               monkeypatch):
    class _Port:
        device, hwid = "/dev/ttyACM0", "USB VID:PID=2341:0043"
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [])
    bar = machine.MachineBar(machine.MachineLink())
    assert "no serial ports" in bar.offline_note.text()
    monkeypatch.setattr(lp, "comports", lambda: [_Port()])
    bar.refresh_ports()
    assert "no serial ports" not in bar.offline_note.text()
    assert bar.connect_btn.isEnabled()
    bar.close()


def test_novice_with_no_ports_is_not_told_to_export(qt_app, monkeypatch):
    """Novice has no export. Nothing plugged in on the CNC PC said it anyway."""
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [])
    monkeypatch.setenv("SRM_CAM_MODE", "novice")
    monkeypatch.setattr(machine, "SHOW_SIM", False)
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))
    bar = machine.MachineBar(machine.MachineLink())
    assert "no serial ports" in bar.offline_note.text()
    assert "VPanel" not in bar.offline_note.text()
    bar.close()


def test_the_simulator_stays_behind_automatic_mode_as_on_the_cnc_pc(qt_app,
                                                                    no_vpanel,
                                                                    monkeypatch):
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [])
    monkeypatch.setattr(machine, "SHOW_SIM", False)
    assert machine.list_ports()[0] == []
    monkeypatch.setattr(machine, "SHOW_SIM", True)
    assert machine.list_ports()[0] == [machine.SIM_ENTRY]


def test_a_system_with_no_link_still_gets_only_the_simulator(qt_app, monkeypatch):
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(
                            machine_link=False, job_routes=(), vpanel=False,
                            link_proven=False))
    bar = machine.MachineBar(machine.MachineLink())
    assert bar.sim_only
    assert bar.port_combo.itemData(0) == sm.SIM_PORT
    assert "not here" in bar.offline_note.text()
    bar.close()


# ------------------------------------------------------------------- the menu
def test_run_this_step_is_in_the_pro_menu_here(win):
    assert win.run_step_act.isVisible()


def test_run_this_step_stays_off_the_menu_on_the_cnc_pc(qt_app, monkeypatch,
                                                        tmp_path):
    monkeypatch.setattr(plat, "documents_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))
    w = MainWindow()
    assert not w.run_step_act.isVisible()
    w.close()


# ---------------------------------------------------- what the plan tells you
def test_the_plan_does_not_send_anyone_to_vpanel_here(no_vpanel):
    assert "VPanel" not in runplan._origin_note()
    assert "Probe Z" in runplan._origin_note()


def test_the_plan_is_unchanged_on_the_cnc_pc(monkeypatch):
    monkeypatch.setattr(plat, "capabilities",
                        lambda p=None: plat.Capabilities(machine_link=True))
    assert runplan._origin_note() is runplan.ORIGIN_NOTE


def test_the_run_sheet_says_how_to_run_each_step_here(win, tmp_path):
    win.export_to(tmp_path)
    text = win.sheet.text()
    assert "VPanel" not in text
    assert "Run this step on the mill" in text


# --------------------------------------------------------- run this step: gates
def test_it_needs_the_link(win):
    said = _says(win)
    win.action_run_step()
    assert "Connect" in said[-1][1]


def test_it_will_not_start_without_a_probe_z(win, qt_app, monkeypatch):
    """Every depth is measured from that touch. No touch, no number."""
    got = _answer(monkeypatch)
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    _pick_step(win)
    said = _says(win)
    win.action_run_step()
    assert "Probe Z" in said[-1][1]
    assert not got


def test_it_says_why_when_there_is_no_way_to_reach_the_mill(win, qt_app,
                                                            monkeypatch):
    got = _answer(monkeypatch)
    # A real port as far as the window can tell; the printer is what is missing.
    monkeypatch.setattr(sm, "is_sim", lambda port: False)
    win.link._ser = object()
    win.link.firmware = {"port": "/dev/ttyACM0", "version": 5, "features": []}
    win.link.surface_z = -10.0
    monkeypatch.setattr(rmlspool, "find_printer", lambda: None)
    monkeypatch.setattr(rmlspool, "no_printer_reason", lambda: "NO MILL HERE")
    _pick_step(win)
    said = _says(win)
    win.action_run_step()
    assert said[-1] == ("fail", "NO MILL HERE")
    assert not got
    win.link._ser = None
    win.link.firmware = None


def test_it_stops_at_a_node_it_may_not_open_before_asking_anything(
        win, qt_app, monkeypatch):
    got = _answer(monkeypatch)
    monkeypatch.setattr(sm, "is_sim", lambda port: False)
    win.link._ser = object()
    win.link.firmware = {"port": "/dev/ttyACM0", "version": 5, "features": []}
    win.link.surface_z = -10.0

    class Refused:
        def problem(self):
            return "NOT ALLOWED"
    monkeypatch.setattr(rmlspool, "find_printer", lambda: Refused())
    _pick_step(win)
    said = _says(win)
    win.action_run_step()
    assert said[-1] == ("fail", "NOT ALLOWED")
    assert not got
    win.link._ser = None
    win.link.firmware = None


def _linked_and_probed(win, qt_app):
    win.link.connect_to("SIM")
    assert _wait(qt_app, win.link.is_connected, 10)
    win.link.surface_z = sm.machine().pos[2] / 1000.0 - 20.0


def test_cancel_sends_nothing(win, qt_app, monkeypatch):
    _answer(monkeypatch, go=False)
    _linked_and_probed(win, qt_app)
    _pick_step(win)
    sent = []
    monkeypatch.setattr(sm, "printer",
                        lambda: type("P", (), {"send": lambda s, d, n: sent.append(n)})())
    win.action_run_step()
    assert not sent


# ---------------------------------------------------- run this step: on the sim
def test_a_step_runs_on_the_simulator_and_the_bar_says_so(win, qt_app, monkeypatch):
    got = _answer(monkeypatch)
    _linked_and_probed(win, qt_app)
    z = win.link.surface_z
    step = _pick_step(win)
    win.bar.said = []
    win.bar.message.connect(lambda l, t: win.bar.said.append((l, t)))
    positions = []
    win.link.position.connect(lambda x, y, z_, t: positions.append((x, y)))
    printer = sm.printer()
    before = len(printer.sent)
    win.action_run_step()
    assert got["title"] == step.title and got["z"] == z
    assert _wait(qt_app, lambda: any("is done" in t for _l, t in win.bar.said),
                 60), win.bar.said
    assert win.link.is_connected()
    programs = printer.sent[before:]
    # The G54 check first, then the job, rendered from the probed Z.
    assert programs[0][0] == "frame check"
    assert programs[1][0].endswith("(dry run)")
    text = programs[1][1]
    assert "G28 Z0." in text and "\nM3\n" not in text


def test_stop_during_a_step_purges_and_says_so(win, qt_app, monkeypatch):
    sm.machine(speedup=30.0, corner=(41300, 27800), angle_deg=0.0,
               size=(150000, 120000))
    _answer(monkeypatch)
    _linked_and_probed(win, qt_app)
    _pick_step(win)
    win.bar.said = []
    win.bar.message.connect(lambda l, t: win.bar.said.append((l, t)))
    win.action_run_step()
    assert _wait(qt_app, lambda: win.link.current_op() == "run_step", 5)
    win.bar._stop()
    assert _wait(qt_app, lambda: win.link.current_op() is None, 30), \
        "the run did not stop"
    assert any("STOP sent" in t for _l, t in win.bar.said)
    assert _wait(qt_app, lambda: any("stopped" in t for _l, t in win.bar.said), 2)
    assert not any("is done" in t for _l, t in win.bar.said)
    # A jog queued behind a job would fire when it ended.
    win.link.clear_abort()


def test_a_jog_is_refused_while_a_step_runs(qt_app, no_vpanel, monkeypatch):
    bar = machine.MachineBar(machine.MachineLink())
    said = []
    bar.message.connect(lambda l, t: said.append(t))
    monkeypatch.setattr(bar.link, "current_op", lambda: "run_step")
    jogged = []
    monkeypatch.setattr(bar.link, "jog_by", lambda **k: jogged.append(k))
    bar._jog(+1)
    assert not jogged and "job is running" in said[-1]
    bar.close()


def test_pause_holds_a_step_with_the_flag_its_loop_reads(qt_app):
    link = machine.MachineLink()
    link._current = "run_step"
    link._ser = None
    assert link.pause() is True and link.should_pause()
    assert link.resume() is True and not link.should_pause()


# -------------------------------------------------------- setting up USB access
def _click(dialog_fn, label, monkeypatch):
    def execute(self):
        for b in self.findChildren(QPushButton):
            if b.text() == label:
                b.click()
                return 0
        raise AssertionError(f"no {label} button")
    monkeypatch.setattr(dialogs.Sheet, "exec", execute)
    return dialog_fn()


class _Parent(dialogs.QWidget):
    def __init__(self):
        super().__init__()
        self.said = []

    def say(self, level, text):
        self.said.append((level, text))


@pytest.fixture
def linux_rules(monkeypatch):
    monkeypatch.setattr(plat, "udev_rules", lambda p=None: "RULES\n")


def test_install_goes_through_pkexec_with_the_bundles_libraries_taken_out(
        qt_app, linux_rules, monkeypatch):
    import shutil
    import subprocess
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pkexec")
    ran = []

    def fake_run(argv, **kw):
        # The file has to exist while the installer reads it.
        src = re.search(r"install -m 0644 (\S+) ", argv[3]).group(1)
        ran.append((argv, kw, Path(src.strip("'")).read_text()))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    p = _Parent()
    assert _click(lambda: dialogs.usb_access_dialog(p), "Install",
                  monkeypatch) == "installed"
    argv, kw, content = ran[0]
    assert argv[:3] == ["/usr/bin/pkexec", "sh", "-c"]
    assert plat.UDEV_RULES_PATH in argv[3]
    assert content == "RULES\n"
    assert kw["env"]["LC_ALL"] == "C"
    assert p.said[-1][0] == "ok"


def test_a_refused_password_is_said_and_the_dialog_stays_honest(
        qt_app, linux_rules, monkeypatch):
    import shutil
    import subprocess
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pkexec")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 126, "", "denied"))
    p = _Parent()
    assert _click(lambda: dialogs.usb_access_dialog(p), "Install",
                  monkeypatch) == "failed"
    assert p.said[-1][0] == "fail" and "denied" in p.said[-1][1]


def test_no_pkexec_puts_the_command_on_the_clipboard(qt_app, linux_rules,
                                                     monkeypatch):
    import shutil
    import subprocess
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: pytest.fail("nothing to run"))
    monkeypatch.setenv("APPIMAGE", "/home/a b/SRM-CAM.AppImage")
    p = _Parent()
    assert _click(lambda: dialogs.usb_access_dialog(p), "Install",
                  monkeypatch) == "copied"
    text = QApplication.clipboard().text()
    assert text.startswith("'/home/a b/SRM-CAM.AppImage' --udev-rule | sudo tee")


def test_no_udev_no_dialog(qt_app, monkeypatch):
    monkeypatch.setattr(plat, "udev_rules", lambda p=None: None)
    assert dialogs.usb_access_dialog(_Parent()) is None


# ---------------------------------------------------------- this host, honestly
@pytest.mark.host_capabilities
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux host")
def test_on_this_linux_host_the_bar_is_not_simulator_only(qt_app, monkeypatch):
    import serial.tools.list_ports as lp
    monkeypatch.setattr(lp, "comports", lambda: [])
    bar = machine.MachineBar(machine.MachineLink())
    assert bar.sim_only is False
    assert "Windows" not in bar.offline_note.text()
    bar.close()


# ------------------------------------------------------------- the documents
@pytest.mark.parametrize("name", ["README.md", "docs/usage.md",
                                  "website/getting-started.html",
                                  "website/hardware.html",
                                  "website/machine-control.html",
                                  "website/troubleshooting.html"])
def test_no_document_still_says_the_link_is_windows_only(name):
    text = (ROOT / name).read_text(encoding="utf-8").lower()
    # "VPanel is Windows-only" is still true, so this looks for the claim itself.
    for stale in ("link is windows-only", "link runs on windows only",
                  "link itself runs on windows only", '"badge copper">windows only',
                  "does not do:** the machine link"):
        assert stale not in text, f"{name} still says {stale!r}"
