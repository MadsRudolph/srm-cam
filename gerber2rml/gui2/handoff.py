"""Open a board in the SRM-CAM that is already running.

The KiCad plugin's "Send to SRM-CAM" button plots the board and hands the
folder over. If a window is already up, the folder goes to it over a local
socket (a named pipe on Windows) instead of starting a second copy, which
would fight the first for the serial port. If none is up, the plugin starts
SRM-CAM with the folder as its argument, and this module's server takes the
next one.

The message is one line of JSON, ``{"open": "<path>"}``, answered by one line:
``ok``, or ``busy`` when a run is in progress and the board was not loaded.
"""
import json
import os

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from gerber2rml import platform as plat


def openable(path):
    """Is ``path`` something SRM-CAM opens from outside: a Gerber folder or a
    saved setup?"""
    return bool(path) and (os.path.isdir(path) or (
        path.lower().endswith(".srmcam") and os.path.isfile(path)))


def paths_in(argv):
    """The openable paths on a command line, first one first."""
    return [os.path.abspath(a) for a in argv[1:] if openable(a)]


def forward(path, address=None, timeout_ms=1500):
    """Give ``path`` to a running SRM-CAM. Returns its answer, or None when
    nothing is listening (start a window then)."""
    sock = QLocalSocket()
    sock.connectToServer(address or plat.handoff_address())
    if not sock.waitForConnected(timeout_ms):
        return None
    sock.write((json.dumps({"open": path}) + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    answer = None
    if sock.waitForReadyRead(timeout_ms):
        answer = bytes(sock.readLine()).decode("utf-8", "replace").strip()
    sock.disconnectFromServer()
    return answer or "ok"


class Server(QObject):
    """Listens for paths and gives each to ``on_open(path) -> bool``."""

    def __init__(self, on_open, address=None, parent=None):
        super().__init__(parent)
        self._on_open = on_open
        self._address = address or plat.handoff_address()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._accept)

    def listen(self):
        """Start listening. A socket file left by a crashed copy is removed
        first; a live copy would have answered :func:`forward` already."""
        QLocalServer.removeServer(self._address)
        return self._server.listen(self._address)

    def close(self):
        self._server.close()

    def _accept(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        if not sock.canReadLine():
            return
        line = bytes(sock.readLine()).decode("utf-8", "replace")
        try:
            path = json.loads(line).get("open")
        except (ValueError, AttributeError):
            path = None
        ok = bool(path) and openable(path) and self._on_open(path)
        sock.write(b"ok\n" if ok else b"busy\n")
        sock.flush()
