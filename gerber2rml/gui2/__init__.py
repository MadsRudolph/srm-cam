"""SRM-CAM's second interface.

An independent front end over the same engine as ``gerber2rml.gui``: it shares
``gerber2rml.app.state.ProjectState``, ``cli.build_jobs``, ``doublesided`` and
the ``engine`` package, and imports nothing from the first interface. Both are
installed side by side so they can be compared on a real job rather than in the
abstract — see ``docs/AB-setup-sheet.md``.

Entry point: ``srm-cam`` (or ``python -m gerber2rml.gui2``).
"""
__all__ = ["main"]


def main(argv=None):
    """Launch the interface. Imported lazily so ``import gerber2rml.gui2`` stays
    cheap for anything that only wants the version or the docstring."""
    from gerber2rml.gui2.app import main as _main
    return _main(argv)
