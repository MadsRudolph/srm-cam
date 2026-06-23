"""Machine backends: name -> Backend(render fn, file extension).

The pluggable seam. ``render`` maps toolpaths to machine-program text; ``ext``
is the file extension the GUI/CLI write. Both SRM-20 entries target the same
mill -- they differ only in the command set VPanel is set to stream:
RML-1 (``.rml``) or NC code / G-code (``.nc``).
"""
from collections import namedtuple
from gerber2rml.backends import srm20, gcode

Backend = namedtuple("Backend", ["render", "ext"])

# G-code (NC) first so it is the default in the GUI dropdown (which opens on the
# first entry) and the CLI. NC is what we use on the SRM-20 -- it honours the
# work Z origin, so retracts stay small; RML is kept only as a fallback.
BACKENDS = {
    "Roland SRM-20 (G-code)": Backend(gcode.render, ".nc"),
    "Roland SRM-20": Backend(srm20.render, ".rml"),
}

DEFAULT_MACHINE = "Roland SRM-20 (G-code)"   # NC / G-code
