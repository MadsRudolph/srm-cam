"""Job names that are safe as a file name and inside a machine program.

The name reaches the disk (``<name>_traces.nc``) and the program header. It
comes from a folder name, the operator, or a setup file someone else shared,
so it can hold anything: ``..\\`` to write outside the export folder, a
newline to end a G-code comment and start real moves, characters Windows
refuses in a file name. One cleaner, applied wherever a name is set or used.
"""
import re

_BAD = re.compile(r"[^A-Za-z0-9 _+.\-æøåÆØÅ]")
MAX_LEN = 60


def clean_name(text, fallback="board"):
    """``text`` reduced to letters, digits, space, ``_ + . -``; no leading
    dots or spaces, no ``..``, at most ``MAX_LEN`` characters."""
    s = _BAD.sub("_", str(text or ""))
    s = s.replace("..", "_").strip(" .")[:MAX_LEN].strip(" .")
    return s or fallback
