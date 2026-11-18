"""How much wider this screen sets the interface than the one the layout
budgets in the tests were set on."""


def ui_scale():
    """How much wider this screen sets the interface's words than the
    screen the budgets below were set on, never less than 1.

    The sizes are points at 96 dpi: a screen (or a CI runner) at 120 dpi
    draws every word a quarter wider, and a machine without the interface's
    faces sets them in wider fallbacks. Both are measured here directly, as
    the width of one line of the bar's own words in the body face, against
    the 380.8 px it measured where the budgets were set."""
    from PySide6.QtGui import QFontMetricsF, QGuiApplication
    from gerber2rml.gui2 import theme
    line = ("Isolation traces 42% Probe Z Pause Click to jog Disconnect "
            "STOP")
    text = QFontMetricsF(theme.font("body")).horizontalAdvance(line) / 380.8
    screen = QGuiApplication.primaryScreen()
    dpi = (screen.logicalDotsPerInch() if screen is not None else 96.0) / 96.0
    return max(1.0, text, dpi)
