"""`python -m gerber2rml.gui` opens the first interface.

The plain `python -m gerber2rml` is the setup sheet now; this is
the source-checkout spelling of `SRM-CAM --original`.
"""
from gerber2rml.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
