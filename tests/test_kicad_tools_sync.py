"""The KiCad plugin is told the cutter in use whenever it changes, not only at
launch - a ball-mill profile (0.44 mm) chosen after start-up used to leave
the plugin asking for 0.8 mm clearances."""
import json
from types import SimpleNamespace

from gerber2rml.gui2 import kicadsetup
from gerber2rml.engine import kicadplugin


def _parent(cutter, drill=0.8):
    trace = SimpleNamespace(effective_diameter=lambda: cutter)
    return SimpleNamespace(state=SimpleNamespace(
        trace=trace, drill=SimpleNamespace(bit_diameter=drill)))


def test_a_new_cutter_is_written_to_every_installed_plugin(tmp_path,
                                                            monkeypatch):
    plug = tmp_path / "srm20area"
    plug.mkdir()
    (plug / kicadplugin.LAUNCH_FILE).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(kicadsetup, "plugin_dirs", lambda: [tmp_path])
    monkeypatch.setattr(kicadplugin, "refresh_launch_info",
                        lambda dirs, info: [kicadplugin.write_launch_info(
                            plug, info)])
    p = _parent(0.44)
    assert kicadsetup.sync_tools(p) is True
    info = json.loads((plug / kicadplugin.LAUNCH_FILE).read_text("utf-8"))
    assert info["cutter_mm"] == 0.44 and info["drill_mm"] == 0.8
    # Unchanged: nothing written again.
    assert kicadsetup.sync_tools(p) is False
    p.state.trace.effective_diameter = lambda: 0.8
    assert kicadsetup.sync_tools(p) is True
