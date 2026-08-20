"""Install the SRM-20 build-area plugin into KiCad.

The board a student designs has to fit the machine that will cut it, and KiCad
has no idea what an SRM-20 is. The plugin draws the machine's build area in the
PCB editor so the answer is visible while there is still time to act on it.

Getting a plugin into KiCad means copying a folder into a path that depends on
the OS and the KiCad version, which is not a thing to ask a first-semester
student to do. SRM-CAM knows where the folder is and can do it for them, which
is what this module is: no Qt, no pcbnew, just file layout.
"""
import os
import shutil
import sys
from pathlib import Path

# The folder name our plugin occupies inside KiCad's plugins directory. Fixed,
# so a reinstall replaces the previous copy instead of leaving two.
PLUGIN_DIRNAME = "srm20_build_area"


def _version_key(name):
    """('10.0') -> (10, 0). Raises ValueError for a non-version folder name."""
    return tuple(int(part) for part in name.split("."))


def plugin_dirs(config_root):
    """KiCad scripting-plugin directories under *config_root*, newest first.

    KiCad keeps one config tree per version (``<root>/10.0/``), and a machine
    that has been upgraded keeps the old ones. Newest first because that is
    the one the student is running; the others are offered, not chosen.
    """
    root = Path(config_root)
    if not root.is_dir():
        return []
    found = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            key = _version_key(child.name)
        except ValueError:
            continue                     # colors/, templates/, ... not a version
        plugins = child / "scripting" / "plugins"
        if plugins.is_dir():
            found.append((key, plugins))
    return [path for _key, path in sorted(found, reverse=True)]


def install(source, plugins_dir):
    """Copy the plugin from *source* into KiCad's *plugins_dir*.

    Returns the installed folder. Any previous copy is removed first rather
    than merged, so a file dropped from a later version cannot linger and
    shadow the new one.
    """
    dest = Path(plugins_dir) / PLUGIN_DIRNAME
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


MISSING, OUTDATED, CURRENT = "missing", "outdated", "current"


def installed_version(plugins_dir):
    """Version of our plugin already in *plugins_dir*, or None if not there."""
    marker = Path(plugins_dir) / PLUGIN_DIRNAME / "VERSION"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def status(plugins_dir, bundled):
    """One of MISSING / OUTDATED / CURRENT for the copy in *plugins_dir*.

    A version that simply differs counts as OUTDATED rather than comparing
    order: if the installed copy is somehow newer than ours, overwriting it
    with the one this app was tested against is still the right move.
    """
    have = installed_version(plugins_dir)
    if have is None:
        return MISSING
    return CURRENT if have == bundled else OUTDATED


def config_roots(platform=None, env=None, home=None):
    """Where KiCad keeps its per-version config trees on this machine.

    A list rather than one path so a future second location (a portable
    install, say) can be added without changing every caller.
    """
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)

    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return [base / "kicad"]
    if platform == "darwin":
        return [home / "Library" / "Preferences" / "kicad"]
    return [home / ".config" / "kicad"]


# The folder shipped alongside the app. Resolves both from a source checkout
# (repo-root/kicad-plugin) and from a PyInstaller build, where the spec drops
# it under sys._MEIPASS — same arrangement as the preload demo board.
def bundled_source():
    """Path to the plugin folder this app ships."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[2]
    return root / "kicad-plugin"


def bundled_version():
    """Version string of the plugin this app ships."""
    return (bundled_source() / "VERSION").read_text(encoding="utf-8").strip()


def should_offer(plugins_dirs, bundled, declined=None):
    """Is it worth asking to install/update the plugin at launch?

    Only when KiCad is actually here, something is missing or stale, and the
    user has not already said no to this exact version. A prompt that comes
    back every launch is one people learn to dismiss unread.
    """
    if not plugins_dirs:
        return False                        # no KiCad on this machine
    if declined == bundled:
        return False                        # asked, answered, same version
    return any(status(d, bundled) != CURRENT for d in plugins_dirs)
