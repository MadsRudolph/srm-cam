"""Frozen-app entry point.

PyInstaller bundles this single script; it hands off to one of the two
interfaces' ``main()``. Kept separate from ``gerber2rml/__main__.py`` so the
build target is explicit and PyInstaller's import graph starts from a plain
module rather than a package ``__main__``.

Both interfaces, from one bundle, because they are the same program: the same
engine, the same ``ProjectState``, the same output files. Building two would
duplicate a ~400 MB Qt/NumPy payload to change one import. A source checkout
has ``python -m gerber2rml.gui2`` and ``python -m gerber2rml``; an installed
copy has this flag, and a desktop entry for each.

**SRM-CAM is the second interface now.** The A/B in docs/HANDOFF-gui-ab.md is
decided: the setup sheet is what the lab is migrating to, so it is what an
installed copy opens with no arguments. The first interface is still here and
still built - a migration is not a deletion, and it stays reachable while
anyone is still using it - but it is now the one you have to ask for.
"""
import sys

# The first interface. A long option rather than a subcommand: a .desktop Exec
# line is a command, and `SRM-CAM --original` reads as one where `SRM-CAM
# original` reads as a file that failed to open.
ORIGINAL_FLAG = "--original"

# What --original used to be the other side of, back when the first interface
# was the default. Accepted and ignored: it is spelled into desktop entries,
# Start-menu shortcuts and shell history on machines that are already out
# there, and having them silently open the wrong interface would be worse than
# a dead option. It selects the second interface, which is now the default, so
# it does exactly what it always did.
SETUP_SHEET_FLAG = "--setup-sheet"

_FLAGS = (ORIGINAL_FLAG, SETUP_SHEET_FLAG)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    original = ORIGINAL_FLAG in argv[1:]
    # Qt parses argv itself and warns about options it does not know, so the
    # ones meant for us never reach it.
    argv = argv[:1] + [a for a in argv[1:] if a not in _FLAGS]
    if original:
        from gerber2rml.gui.app import main as gui_main
        return gui_main()
    from gerber2rml.gui2.app import main as gui_main
    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
