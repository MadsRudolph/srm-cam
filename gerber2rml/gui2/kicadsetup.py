"""Put the SRM-20 build-area button into KiCad, from the setup sheet.

The board a student designs has to fit the machine that will cut it, and
KiCad has no idea what an SRM-20 is. The plugin (``kicad-plugin/``) draws
the build area in the PCB editor while there is still time to act on it.
The engine (:mod:`gerber2rml.engine.kicadplugin`) knows where KiCad keeps
plugins on each OS and copies the folder; this is what the sheet says
about it.

Two ways in: **KiCad → Set up the build-area plugin…**, and an offer at
launch, once per plugin version, only when KiCad is actually on the
machine and the plugin is missing or stale.
"""
from gerber2rml.engine import kicadplugin
from gerber2rml.gui2 import dialogs, tier

# "_2" from 0.23.1: everyone who said "Not now" before is asked once more.
DECLINED_KEY = "kicad/declined_plugin_version_2"
MENU_LOCATION = "Tools → External Plugins → Show SRM-20 build area"
SEND_LOCATION = "Tools → External Plugins → Send to SRM-CAM"
RULES_LOCATION = "Tools → External Plugins → Set design rules for SRM-CAM"


def _launch_info(parent):
    """Where this app is, and the cutter and drill it works with - the
    plugin's design-rule check needs those
    (kicad-plugin/srm20area/rules.py)."""
    info = kicadplugin.launch_info()
    try:
        info["cutter_mm"] = round(
            float(parent.state.trace.effective_diameter()), 3)
        info["drill_mm"] = round(float(parent.state.drill.bit_diameter), 3)
    except Exception:                                # noqa: BLE001 - optional
        pass
    return info


def sync_tools(parent):
    """Tell the KiCad plugin about the cutter and drill now in use, when they
    have changed since it was last told. Its design-rule check asks for the
    cutter's width: written only at launch, it kept the 0.8 mm of whatever
    profile came up first, and a board for the 0.44 mm ball mill was refused.
    Best effort, and cheap when nothing changed."""
    try:
        info = _launch_info(parent)
        tools = (info.get("cutter_mm"), info.get("drill_mm"))
        if tools == getattr(parent, "_kicad_tools", None):
            return False
        kicadplugin.refresh_launch_info(plugin_dirs(), info)
        parent._kicad_tools = tools
        return True
    except Exception:                                # noqa: BLE001 - a nicety
        return False


def plugin_dirs():
    dirs = []
    for root in kicadplugin.config_roots():
        dirs.extend(kicadplugin.plugin_dirs(root))
    return dirs


def setup(parent, settings=None):
    """Install into every KiCad found, and say where it went. Returns the
    installed folders (empty when KiCad is absent or every copy failed)."""
    settings = settings or tier._settings()
    dirs = plugin_dirs()
    if not dirs:
        roots = "\n".join(f"    {r}" for r in kicadplugin.config_roots())
        d = dialogs.Sheet(parent, "KiCad was not found on this PC", width=560)
        d.say("Install KiCad first, then run this again. SRM-CAM itself does "
              "not need KiCad; it only reads the Gerbers KiCad exports.")
        d.say("Looked in:\n" + roots, small=True, mono=True)
        d.setObjectName("kicadSheet")
        d.act("Close", kind="primary", on=d.accept, default=True)
        d.exec()
        return []

    done, failed = [], []
    info = _launch_info(parent)
    for dir_ in dirs:
        try:
            dest = kicadplugin.install(kicadplugin.bundled_source(), dir_)
            kicadplugin.write_launch_info(dest, info)
            done.append(dest)
        except Exception as e:                       # noqa: BLE001 - permissions, mostly
            failed.append(f"{dir_}\n    {e}")

    if not done:
        dialogs.report_error(
            parent, "The plugin could not be copied into KiCad",
            RuntimeError("\n".join(failed)),
            "Check that the folders above are writable, or copy the "
            "kicad-plugin folder there by hand as kicad-plugin/README.md "
            "describes.")
        return []

    d = dialogs.Sheet(parent, "The KiCad plugin is installed", width=560)
    d.say(f"Restart KiCad, then find it in the PCB editor under "
          f"{MENU_LOCATION}. It draws the build area on User.Drawings and "
          "says whether the board fits.")
    d.say(f"Beside it are {RULES_LOCATION}, which sets the design rules "
          "for how the board is made (flat endmill, ball mill or fiber "
          f"laser), and {SEND_LOCATION}: it plots the board and opens it "
          "here, ready to run. It first checks that the board's design "
          "rules suit its method, and offers to set them. All three are on "
          "the toolbar too.")
    d.say("Installed to:\n" + "\n".join(f"    {p}" for p in done),
          small=True, mono=True)
    if failed:
        d.say("Some locations failed:\n" + "\n".join(failed), small=True,
              mono=True)
    d.setObjectName("kicadSheet")
    d.act("Close", kind="primary", on=d.accept, default=True)
    d.exec()
    settings.remove(DECLINED_KEY)      # they have it; a new version may ask
    return done


def should_offer(settings=None):
    """Is the launch-time offer worth making on this machine right now?"""
    settings = settings or tier._settings()
    try:
        declined = settings.value(DECLINED_KEY) or None
        return kicadplugin.should_offer(plugin_dirs(),
                                        kicadplugin.bundled_version(), declined)
    except Exception:                                # noqa: BLE001 - never at launch
        return False


def maybe_offer(parent, settings=None):
    """The launch offer. True if it was shown. Best-effort throughout: a
    locked-down profile or an unreadable folder must not stop the app."""
    settings = settings or tier._settings()
    try:
        # Keep "Send to SRM-CAM" pointing at this copy of the app, wherever
        # it has been moved since the plugin was installed.
        kicadplugin.refresh_launch_info(plugin_dirs(), _launch_info(parent))
    except Exception:                                # noqa: BLE001 - never at launch
        pass
    if not should_offer(settings):
        return False
    d = dialogs.Sheet(parent, "Add the SRM-20 buttons to KiCad?", width=560)
    d.say("KiCad is installed on this PC. SRM-CAM can add three buttons to "
          "its PCB editor: one draws the mill's build area and says whether "
          "your board fits, while there is still time to change it rather "
          "than at the machine; one sets the design rules for how the board "
          "is made; the third sends the board straight here.")
    d.say("You can do this later from the KiCad menu.", small=True)
    d.setObjectName("kicadOffer")
    out = {"go": False}

    def go():
        out["go"] = True
        d.accept()

    d.act("Not now", on=d.reject)
    d.act("Add it", kind="primary", on=go, default=True)
    # In front of the window, never behind it: a modal sheet nobody can see
    # leaves the whole app looking frozen.
    d.show()
    d.raise_()
    d.activateWindow()
    d.exec()
    if out["go"]:
        setup(parent, settings)
    else:
        settings.setValue(DECLINED_KEY, kicadplugin.bundled_version())
    return True
