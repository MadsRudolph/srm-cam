"""Frozen-app entry point.

PyInstaller bundles this single script; it just hands off to the GUI's main().
Kept separate from gerber2rml/__main__.py so the build target is explicit and
PyInstaller's import graph starts from a plain module rather than a package
__main__.
"""
from gerber2rml.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
