"""How this program asks for an OpenGL context, in one place.

Both interfaces open 3D views (the toolpath simulator, and the first
interface's bed visualizer), both drive them through pyqtgraph, and pyqtgraph
is particular about the context it is handed. Getting that wrong does not
raise where you are looking: the window opens and renders nothing, or the
constructor throws from inside a Qt event callback and the traceback names
``ev.type()`` in an unrelated event filter.

It lived as a private function in ``gui/app.py`` and the second interface
never got a copy, so ``gui2``'s simulator raised on any machine whose driver
needed the request spelled out - every Linux box, as it turns out. Same
argument as ``platform.py``: one module, so the two interfaces cannot drift.

Two entry points, because there are two moments:

``configure()`` runs BEFORE the QApplication exists and is the real fix - the
backend attributes it sets are only read while Qt is starting up.

``ensure_default_format()`` is the safety net for a 3D window opened by code
that never went through ``main()`` (the test suite, mostly). It can raise the
default surface format's version after the fact, which is the part pyqtgraph
actually checks, but it cannot change the backend.

No Qt import at module scope: ``gui2/app.py`` imports this before it has
established that PySide6 is importable at all.
"""
import os

# pyqtgraph 0.14 refuses a context below this - GLViewWidget.initializeGL
# raises "Requires >= OpenGL 2.1". It reads QSurfaceFormat.version(), which is
# what was ASKED FOR, not what the driver can do; Qt's default request on
# Linux is (2, 0), so an NVIDIA card advertising 4.6 is still rejected. Ask
# for 2.1 and the same card is accepted. It is a floor, not a ceiling: drivers
# hand back the highest compatible context they have.
MIN_VERSION = (2, 1)


def _fmt_module():
    from PySide6.QtGui import QSurfaceFormat
    return QSurfaceFormat


def backend(env=None):
    """Which OpenGL driver to ask Qt for: ``desktop``, ``software`` or ``angle``.

    ``desktop`` is the default on every platform. On Windows Qt often picks an
    ANGLE (OpenGL-ES-over-Direct3D) context on its own, under which pyqtgraph's
    desktop GLSL shaders fail to link - ``GL_INVALID_VALUE`` on ``glUseProgram``
    - and the 3D view draws nothing. ``GERBER2RML_GL`` overrides it:
    ``software`` (Mesa llvmpipe) for a machine with no usable GPU driver -
    headless, RDP, a VM - and ``angle`` to restore the old Windows behaviour.

    Note for Linux: Qt's own ``QT_OPENGL`` variable is a Windows-only knob.
    ``GERBER2RML_GL=software`` is the portable way to ask for llvmpipe, and it
    is what CI sets.
    """
    env = os.environ if env is None else env
    mode = env.get("GERBER2RML_GL", "desktop").lower()
    return mode if mode in ("desktop", "software", "angle") else "desktop"


def configure(env=None):
    """Choose the OpenGL backend and the default surface format.

    Call this *before* constructing the QApplication. Qt reads the application
    attributes while it starts up; setting them afterwards is silently ignored,
    which is why this is a separate call and not part of window construction.
    """
    from PySide6.QtCore import Qt, QCoreApplication
    QSurfaceFormat = _fmt_module()

    attr = {
        "desktop": Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
        "software": Qt.ApplicationAttribute.AA_UseSoftwareOpenGL,
        "angle": Qt.ApplicationAttribute.AA_UseOpenGLES,
    }[backend(env)]
    QCoreApplication.setAttribute(attr, True)

    # Share GL resources across contexts. Without this, closing a 3D window
    # destroys its GL context and invalidates pyqtgraph's cached shader
    # programs; the next window gets a fresh, non-sharing context and
    # glUseProgram fails (GL_INVALID_VALUE) -> blank. Sharing keeps the
    # programs valid across windows.
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    fmt = QSurfaceFormat()
    fmt.setVersion(*MIN_VERSION)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)


def ensure_default_format():
    """Raise the default surface format to :data:`MIN_VERSION` if it is below it.

    Unlike :func:`configure` this is safe to call at any time, and is what the
    3D window modules call as they are imported - a window opened by code that
    never ran ``main()`` still gets a context pyqtgraph will accept. It only
    ever raises the version, never lowers it, so calling it after
    :func:`configure` changes nothing.

    Returns True if it changed the default.
    """
    QSurfaceFormat = _fmt_module()
    current = QSurfaceFormat.defaultFormat()
    if tuple(current.version()) >= MIN_VERSION:
        return False
    fmt = QSurfaceFormat(current)
    fmt.setVersion(*MIN_VERSION)
    QSurfaceFormat.setDefaultFormat(fmt)
    return True
