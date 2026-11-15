"""KiCad's "Send to SRM-CAM" button, and SRM-CAM's side of the hand-over.

The plugin module is pure (no pcbnew, no wx), loaded straight off disk the
way KiCad would. Nothing here runs the real kicad-cli or touches KiCad's
folders; the plot itself was checked against KiCad 10 by hand
(docs/macos.md).
"""
import importlib.util
import json
import os
import subprocess
import types

import pytest

from gerber2rml import platform as plat
from gerber2rml.engine import kicadplugin


def _sendto():
    path = kicadplugin.bundled_source() / "srm20area" / "sendto.py"
    spec = importlib.util.spec_from_file_location("_srm20area_sendto", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_plugin_version_was_bumped_for_the_new_button():
    """An installed 1.0.x copy has no Send button; a new version is what
    makes the launch offer come back and replace it."""
    assert kicadplugin.bundled_version() != "1.0.1"
    assert (kicadplugin.bundled_source() / "action_send_to_srmcam.py").is_file()
    init = (kicadplugin.bundled_source() / "__init__.py").read_text("utf-8")
    assert "SendToSRMCAMAction().register()" in init


def test_kicad_cli_is_found_inside_the_running_kicad_app():
    s = _sendto()
    exe = "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/bin/python3"
    want = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    assert s.find_kicad_cli(exe, "darwin", which=lambda n: None,
                            exists=lambda p: p == want) == want


def test_kicad_cli_is_found_beside_kicad_on_windows():
    s = _sendto()
    exe = r"C:\Program Files\KiCad\9.0\bin\pythonw.exe"
    found = s.find_kicad_cli(exe, "win32", which=lambda n: None,
                             exists=lambda p: p.endswith("kicad-cli.exe"))
    assert found.endswith("kicad-cli.exe")


def test_export_plots_the_layers_srm_cam_reads_and_clears_stale_files(tmp_path):
    s = _sendto()
    out = tmp_path / "srm-cam"
    out.mkdir()
    (out / "board-NPTH.drl").write_text("stale")
    (out / "notes.txt").write_text("keep")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[3] == "gerbers":
            (out / "board-B_Cu.gbl").write_text("G04*")
        return subprocess.CompletedProcess(argv, 0, "", "")
    s.export(str(tmp_path / "board.kicad_pcb"), str(out), "kicad-cli", run=run)
    gerbers, drill = calls
    layers = gerbers[gerbers.index("--layers") + 1].split(",")
    assert {"B.Cu", "F.Cu", "Edge.Cuts"} <= set(layers)
    assert "--excellon-separate-th" in drill
    assert not (out / "board-NPTH.drl").exists()      # a stale drill file
    assert (out / "notes.txt").exists()               # not ours: left alone


def test_export_falls_back_to_one_drill_file_on_older_kicad(tmp_path):
    s = _sendto()
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if "--excellon-separate-th" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "unknown option")
        if argv[3] == "gerbers":
            (tmp_path / "b-B_Cu.gbl").write_text("x")
        return subprocess.CompletedProcess(argv, 0, "", "")
    s.export("b.kicad_pcb", str(tmp_path), "kicad-cli", run=run)
    assert "--excellon-separate-th" not in calls[-1]


def test_export_without_bottom_copper_is_an_error(tmp_path):
    s = _sendto()
    run = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", "")
    with pytest.raises(s.SendError, match="B.Cu"):
        s.export("b.kicad_pcb", str(tmp_path), "kicad-cli", run=run)


def test_a_running_srm_cam_gets_the_folder_and_is_brought_forward(tmp_path):
    s = _sendto()
    app = tmp_path / "SRM-CAM.app"
    app.mkdir()
    started = []
    r = s.open_in_srmcam("/b/srm-cam", {"address": "x", "app": str(app)},
                         platform="darwin", popen=lambda a, **k: started.append(a),
                         ask=lambda addr, p: "ok")
    assert r == "sent"
    assert started == [["open", "-a", str(app)]]


def test_a_busy_srm_cam_is_left_alone():
    s = _sendto()
    started = []
    r = s.open_in_srmcam("/b", {"address": "x"}, platform="darwin",
                         popen=lambda a, **k: started.append(a),
                         ask=lambda addr, p: "busy")
    assert r == "busy" and started == []


def test_srm_cam_is_started_with_the_folder_when_not_running(tmp_path):
    s = _sendto()
    exe = tmp_path / "python"
    exe.write_text("")
    started = []
    r = s.open_in_srmcam("/b/srm-cam",
                         {"argv": [str(exe), "-m", "gerber2rml.gui2"]},
                         platform="linux",
                         popen=lambda a, **k: started.append((a, k)),
                         ask=lambda addr, p: None)
    assert r == "started"
    argv, kw = started[0]
    assert argv == [str(exe), "-m", "gerber2rml.gui2", "/b/srm-cam"]
    assert kw["stdout"] is subprocess.DEVNULL


def test_nothing_to_start_says_so():
    s = _sendto()
    r = s.open_in_srmcam("/b", {}, platform="linux", popen=None,
                         ask=lambda addr, p: None)
    assert r == "missing"


def test_launch_info_for_a_frozen_mac_app():
    exe = "/Applications/SRM-CAM.app/Contents/MacOS/SRM-CAM"
    info = kicadplugin.launch_info(exe, frozen=True, address="sock")
    assert info == {"argv": [exe], "app": "/Applications/SRM-CAM.app",
                    "address": "sock"}


def test_launch_info_for_a_source_checkout():
    info = kicadplugin.launch_info("/venv/bin/python", frozen=False,
                                   address="sock")
    assert info["argv"] == ["/venv/bin/python", "-m", "gerber2rml.gui2"]
    assert info["app"] is None


def test_launch_info_is_written_and_refreshed(tmp_path):
    plugins = tmp_path / "10.0" / "scripting" / "plugins"
    dest = kicadplugin.install(kicadplugin.bundled_source(), plugins)
    kicadplugin.write_launch_info(dest, {"argv": ["old"]})
    kicadplugin.refresh_launch_info([plugins, tmp_path / "nope"],
                                    {"argv": ["new"]})
    s = _sendto()
    assert s.read_launch_info(str(dest)) == {"argv": ["new"]}


def test_the_handoff_address_is_per_user():
    a = plat.handoff_address("darwin", uid=501, tmp="/var/T")
    assert a == "/var/T/srm-cam-501.sock"
    assert plat.handoff_address("darwin", uid=502, tmp="/var/T") != a
    assert plat.handoff_address("win32").startswith("SRM-CAM-")


def test_handoff_round_trip_over_a_real_local_socket(qt_app, tmp_path):
    """SRM-CAM's server, the plugin's POSIX client and the second-launch
    client all speak the same one line."""
    import sys
    from PySide6.QtCore import QCoreApplication
    from gerber2rml.gui2 import handoff
    if sys.platform.startswith("win"):
        address = f"srm-cam-test-{os.getpid()}"
    else:
        # Not tmp_path: a Unix socket path must stay under ~104 characters.
        import tempfile
        address = os.path.join(tempfile.mkdtemp(prefix="srmh"), "h.sock")
    got = []
    server = handoff.Server(lambda p: got.append(p) or True, address=address)
    assert server.listen()
    board = tmp_path / "board"
    board.mkdir()
    import threading
    answers = []
    t = threading.Thread(target=lambda: answers.append(
        _sendto().ask_running(address, str(board))))
    t.start()
    while t.is_alive():
        QCoreApplication.processEvents()
    if not sys.platform.startswith("win"):
        assert answers == ["ok"] and got == [str(board)]
    server.close()
    # Let the closed connection's deleteLater run while the server is still
    # alive; a Server outlives its sockets in the app, and must here too.
    for _ in range(20):
        QCoreApplication.processEvents()
    server.deleteLater()
    QCoreApplication.processEvents()


def test_open_from_outside_refuses_during_a_run(qt_app, tmp_path):
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    loaded = []
    w.load_folder = lambda p: loaded.append(p)
    w.autorun_page._thread = object()             # a run is going
    assert w.open_from_outside(str(tmp_path)) is False
    assert loaded == []
    w.autorun_page._thread = None
    w._detect_sides = lambda: None
    assert w.open_from_outside(str(tmp_path)) is True
    assert loaded == [str(tmp_path)]
    w.close()


def test_arrow_rules_write_svgs_in_the_theme_colour(tmp_path):
    from gerber2rml.gui2 import style, theme
    qss = style.arrow_rules(tmp_path)
    svg = (tmp_path / "down.svg").read_text(encoding="utf-8")
    assert theme.TEXT_2 in svg and "<path" in svg
    assert "QComboBox::down-arrow" in qss and (tmp_path / "down.svg").as_posix() in qss


def test_mac_update_finds_its_checkout(tmp_path, monkeypatch):
    from gerber2rml.gui2 import updatecheck
    monkeypatch.setattr(plat, "_is_macos", lambda platform=None: True)
    repo = tmp_path / "srm-cam"
    (repo / "packaging").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "packaging" / "update-macos.sh").write_text("#!/bin/sh")
    meipass = tmp_path / "bundle"
    meipass.mkdir()
    (meipass / "build_info.json").write_text(json.dumps({"repo": str(repo)}))
    assert updatecheck.mac_checkout(frozen=True, meipass=meipass) == repo
    (repo / ".git").rmdir()
    assert updatecheck.mac_checkout(frozen=True, meipass=meipass) is None
    monkeypatch.setattr(plat, "_is_macos", lambda platform=None: False)
    assert updatecheck.mac_checkout(frozen=True, meipass=meipass) is None


def test_a_mac_checkout_turns_the_download_into_a_rebuild(qt_app, tmp_path,
                                                          monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from gerber2rml.engine import updates
    from gerber2rml.gui2 import updatecheck
    ran = []
    monkeypatch.setattr(updatecheck, "run_mac_update", ran.append)
    result = updates.Result(updates.UPDATE, "9.9.9", "https://x", "", "")
    parent = QWidget()
    d = updatecheck.result_sheet(parent, result, checkout=tmp_path)
    buttons = {b.text(): b for b in d.findChildren(QPushButton)}
    assert "Update now" in buttons and "Open the download page" not in buttons
    buttons["Update now"].click()
    assert ran == [tmp_path]
    d = updatecheck.result_sheet(parent, result)            # no checkout
    assert "Open the download page" in {
        b.text() for b in d.findChildren(QPushButton)}


def test_the_plugin_is_told_which_cutter_srm_cam_isolates_with(qt_app):
    """Its design-rule check needs the width: 0.8 mm for the lab's endmill,
    whatever the tool profile says otherwise."""
    from gerber2rml.gui2 import kicadsetup
    from gerber2rml.gui2.window import MainWindow
    w = MainWindow()
    info = kicadsetup._launch_info(w)
    assert info["cutter_mm"] == pytest.approx(
        w.state.trace.effective_diameter())
    assert info["argv"] and "address" in info
    w.close()


def test_the_rules_action_is_registered_and_never_a_toolbar_button():
    src = (kicadplugin.bundled_source()
           / "action_send_to_srmcam.py").read_text("utf-8")
    assert "class SRM20RulesAction" in src
    assert "self.show_toolbar_button = False" in src
    init = (kicadplugin.bundled_source() / "__init__.py").read_text("utf-8")
    assert "SRM20RulesAction().register()" in init
