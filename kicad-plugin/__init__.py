"""KiCad entry point. pcbnew imports this at startup and we register the plugin.

Installed by SRM-CAM (Help -> Set up the KiCad plugin), which copies this
folder into KiCad's scripting/plugins directory.
"""
import os
import sys

# Make the bundled 'srm20area' package importable regardless of how KiCad loads
# this folder — relative-import behaviour varies across KiCad point releases.
sys.path.insert(0, os.path.dirname(__file__))

try:
    from action_srm20_area import SRM20BuildAreaAction
    SRM20BuildAreaAction().register()
except Exception:      # never break PCB editor startup over a plugin error
    import traceback
    sys.stderr.write("SRM-20 build area failed to register:\n")
    traceback.print_exc()
