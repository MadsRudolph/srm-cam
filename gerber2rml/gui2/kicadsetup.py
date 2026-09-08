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

DECLINED_KEY = "kicad/declined_plugin_version"
MENU_LOCATION = "Tools → External Plugins → Show SRM-20 build area"


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
    for dir_ in dirs:
        try:
            done.append(kicadplugin.install(kicadplugin.bundled_source(), dir_))
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
    if not should_offer(settings):
        return False
    d = dialogs.Sheet(parent, "Add the SRM-20 button to KiCad?", width=560)
    d.say("KiCad is installed on this PC. SRM-CAM can add a button to its "
          "PCB editor that draws the mill's build area and says whether "
          "your board fits, while there is still time to change it rather "
          "than at the machine.")
    d.say("You can do this later from the KiCad menu.", small=True)
    d.setObjectName("kicadOffer")
    out = {"go": False}

    def go():
        out["go"] = True
        d.accept()

    d.act("Not now", on=d.reject)
    d.act("Add it", kind="primary", on=go, default=True)
    d.exec()
    if out["go"]:
        setup(parent, settings)
    else:
        settings.setValue(DECLINED_KEY, kicadplugin.bundled_version())
    return True
