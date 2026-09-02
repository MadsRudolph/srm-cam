"""The second interface's 3D simulator gets built, not just imported.

Nothing in the suite had ever constructed this window - only the first
interface's copy in test_simulate.py - and that is how it came to be broken on
every Linux machine without anyone noticing. It is the same class of gap the
A/B docs keep pointing at: two interfaces, one of them tested.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gerber2rml.toolpath import Move


def _tp(*pts):
    return [Move(x, y, z, rapid) for (x, y, z, rapid) in pts]


# A note on what failure looks like here. If the surface format regresses,
# these tests do not fail cleanly - the process HANGS and has to be killed,
# because pyqtgraph raises from inside initializeGL and the offscreen platform
# deadlocks on it rather than propagating. That is the original symptom, and
# it is why the fast, clean guard lives in test_glconfig.py
# (test_every_3d_window_module_secures_the_format_as_it_imports): that one
# fails in half a second and names the module. This file is the end-to-end
# proof that a window actually opens; read the two together.


def _skip_or_raise(exc):
    """Skip where there is genuinely no GL; fail on the bug this file is for.

    A bare `except: skip` is why the first interface's equivalent test stayed
    green through the whole Linux branch - pyqtgraph's refusal looks exactly
    like "no OpenGL here" from the outside, and gets skipped with it. It is
    not the same thing: the machine had OpenGL 4.6, we just asked for 2.0.
    """
    if "Requires >= OpenGL" in str(exc):
        raise AssertionError(
            "pyqtgraph refused the surface format - gerber2rml.glconfig did "
            f"not take effect: {exc}") from exc
    pytest.skip(f"3D view unavailable: {exc}")


def _window():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from gerber2rml.gui2.sim3d import Simulation3DWindow
    tp = [_tp((2, 2, 2.0, True), (2, 2, -0.15, False),
              (30, 20, -0.15, False), (2, 2, 2.0, True))]
    return Simulation3DWindow, tp


def _realize(w):
    """Show the window and pump the event loop, so a GL context is made.

    Constructing a GLViewWidget touches no OpenGL at all - initializeGL runs
    when the widget is first shown. A test that only constructs one therefore
    passes on a machine where the 3D view is completely broken, which is what
    the first version of this file did.
    """
    from PySide6.QtWidgets import QApplication
    w.resize(400, 300)
    w.show()
    QApplication.instance().processEvents()
    return w


def test_gui2_sim3d_window_opens():
    try:
        Simulation3DWindow, tp = _window()
        w = _realize(Simulation3DWindow(tp, title="smoke"))
    except Exception as e:
        _skip_or_raise(e)
    assert w.view.items, "the scene came up with nothing in it"


def test_gui2_sim3d_gets_a_context_pyqtgraph_accepts():
    """The actual regression: what the GL context reports once it exists.

    pyqtgraph reads QSurfaceFormat.version() - the version REQUESTED - and
    refuses below 2.1. Qt asks for (2, 0) on Linux unless something says
    otherwise, so this is the assertion that fails if glconfig stops being
    called, on a machine whose driver is perfectly capable.
    """
    from gerber2rml import glconfig
    try:
        Simulation3DWindow, tp = _window()
        w = _realize(Simulation3DWindow(tp))
    except Exception as e:
        _skip_or_raise(e)
    ctx = w.view.context()
    if ctx is None:
        pytest.skip("no GL context on this machine at all")
    assert tuple(ctx.format().version()) >= glconfig.MIN_VERSION


def test_gui2_sim3d_window_draws_board_and_bed():
    """Same assertion the first interface's window carries, on the second's."""
    try:
        Simulation3DWindow, tp = _window()
        bare = _realize(Simulation3DWindow(tp))
        full = _realize(Simulation3DWindow(tp, board=(2, 2, 30, 20),
                                           bed=(203.2, 152.4)))
    except Exception as e:
        _skip_or_raise(e)
    assert len(full.view.items) > len(bare.view.items)
