"""Frozen-app entry point.

PyInstaller bundles this single script; it hands off to one of the two
interfaces' ``main()``. Kept separate from ``gerber2rml/__main__.py`` so the
build target is explicit and PyInstaller's import graph starts from a plain
module rather than a package ``__main__``.

Both interfaces, from one bundle, because they are the same program: the same
engine, the same ``ProjectState``, the same output files. Building two would
duplicate a ~400 MB Qt/NumPy payload to change one import. A source checkout
has ``python -m gerber2rml`` and ``python -m gerber2rml.gui2``; an installed
copy has this flag, and a desktop entry for each so both are one keystroke
away.

The interfaces are still undecided (docs/HANDOFF-gui-ab.md): the first is the
default, and nothing here presumes which one the lab ends up keeping.
"""
import sys

# The second interface - "the setup sheet" in the A/B docs. A long option
# rather than a subcommand: a .desktop Exec line is a command, and `SRM-CAM
# --setup-sheet` reads as one where `SRM-CAM setup-sheet` reads as a file that
# failed to open.
SETUP_SHEET_FLAG = "--setup-sheet"


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if SETUP_SHEET_FLAG in argv[1:]:
        argv = [a for a in argv if a != SETUP_SHEET_FLAG]
        from gerber2rml.gui2.app import main as gui_main
        return gui_main(argv)
    from gerber2rml.gui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
