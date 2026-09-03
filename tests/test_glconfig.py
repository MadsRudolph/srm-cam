"""The OpenGL context both interfaces ask for.

The bug these exist for: Qt's default surface format on Linux asks for OpenGL
2.0, pyqtgraph 0.14 refuses anything below 2.1, and it checks the format that
was REQUESTED rather than what the driver can do - so a card advertising 4.6
was rejected. It does not fail where you would look, either: the refusal is
raised inside initializeGL, which surfaces as a SystemError from whatever
event filter happens to be running, and under an offscreen platform the whole
test simply hangs. The first interface set the format in main() and was fine;
the second never did, and neither does any test that builds a 3D window
directly.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QSurfaceFormat

from gerber2rml import glconfig


def test_backend_defaults_to_desktop():
    assert glconfig.backend({}) == "desktop"


def test_backend_reads_the_override():
    assert glconfig.backend({"GERBER2RML_GL": "software"}) == "software"
    assert glconfig.backend({"GERBER2RML_GL": "angle"}) == "angle"
    assert glconfig.backend({"GERBER2RML_GL": "SOFTWARE"}) == "software"


def test_backend_falls_back_on_a_value_it_does_not_know():
    # Matches the pre-refactor dict .get(mode, DESKTOP): a typo in the
    # variable must not leave the app with no backend selected at all.
    assert glconfig.backend({"GERBER2RML_GL": "vulkan"}) == "desktop"


def test_ensure_default_format_raises_a_version_below_the_minimum():
    fmt = QSurfaceFormat()
    fmt.setVersion(2, 0)                      # what Qt hands out on Linux
    QSurfaceFormat.setDefaultFormat(fmt)
    assert glconfig.ensure_default_format() is True
    assert tuple(QSurfaceFormat.defaultFormat().version()) >= glconfig.MIN_VERSION


def test_ensure_default_format_leaves_a_higher_version_alone():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 6)
    QSurfaceFormat.setDefaultFormat(fmt)
    assert glconfig.ensure_default_format() is False
    assert tuple(QSurfaceFormat.defaultFormat().version()) == (4, 6)


@pytest.mark.parametrize("module", [
    "gerber2rml.gui.bedviz",
    "gerber2rml.gui.sim3d",
    "gerber2rml.gui2.sim3d",
    "gerber2rml.gui2.bedviz",
])
def test_every_3d_window_module_secures_the_format_as_it_imports(module):
    """Importing a 3D window is enough; nothing has to remember to call main().

    Each of these modules opens a GLViewWidget, and each can be reached
    without going through either interface's main() - which is exactly how
    the test suite reaches them.
    """
    import importlib
    fmt = QSurfaceFormat()
    fmt.setVersion(2, 0)
    QSurfaceFormat.setDefaultFormat(fmt)
    importlib.reload(importlib.import_module(module))
    assert tuple(QSurfaceFormat.defaultFormat().version()) >= glconfig.MIN_VERSION
