"""Phone hand-off dialog: QR code -> phone camera page -> photo lands here.

Two transports, picked by the Relay field (remembered across sessions):

- Relay URL set  -> phone and app both talk to the self-hosted Cloudflare
  relay (relay/worker.js). Works on ANY network — eduroam, mobile data —
  because the PC accepts no inbound traffic at all.
- Relay empty    -> direct LAN mode: a one-shot local server + a QR with
  this PC's address. Zero infrastructure, but phone and PC must be able
  to reach each other (client-isolating wifi blocks this).

Either way, ``photo_path`` holds the saved file after accept().
"""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QLineEdit, QVBoxLayout)

from gerber2rml.engine import photorelay
from gerber2rml.engine.photoshare import PhotoShareServer
from gerber2rml.gui.workspace import _settings

# The team relay (relay/worker.js on Cloudflare). Used when the Relay
# field is empty, so the dialog works on any network with zero setup;
# type "lan" in the field for the direct local-server mode instead.
DEFAULT_RELAY = "https://srm-cam-relay.madsrudolph.dev"
_LAN_WORDS = ("lan", "local", "direct")


def qr_pixmap(text, module_px=7):
    """Render ``text`` as a QR code QPixmap (no PIL — painted from the
    module matrix). White quiet zone kept: scanners need the contrast."""
    import qrcode
    q = qrcode.QRCode(border=2)
    q.add_data(text)
    q.make(fit=True)
    matrix = q.get_matrix()
    n = len(matrix)
    img = QImage(n * module_px, n * module_px, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(x * module_px, y * module_px, module_px, module_px)
    p.end()
    return QPixmap.fromImage(img)


class _Bridge(QObject):
    # emitted from a worker thread; auto-queued to the GUI thread
    received = Signal(str)


class PhonePhotoDialog(QDialog):
    def __init__(self, parent, save_dir):
        super().__init__(parent)
        self.setWindowTitle("Photo from phone")
        self.photo_path = None
        self.save_dir = save_dir
        self._bridge = _Bridge()
        self._bridge.received.connect(self._on_received)
        self._server = None
        self._poller = None

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        head = QLabel("Scan with the phone camera, then take the photo:")
        head.setWordWrap(True)
        lay.addWidget(head)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.qr_label)
        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setToolTip("Or type this address in the phone browser.")
        lay.addWidget(self.url_edit)

        relay_row = QHBoxLayout()
        relay_row.addWidget(QLabel("Relay"))
        self.relay_edit = QLineEdit(
            str(_settings().value("phone/relay_url", "")))
        self.relay_edit.setPlaceholderText(
            f"empty = {DEFAULT_RELAY} · 'lan' = direct")
        self.relay_edit.setToolTip(
            "Photo relay (relay/README.md). Empty uses the team relay — "
            "the phone then works on ANY network, eduroam and mobile data "
            "included. Enter another relay URL to use your own, or type "
            "'lan' for direct LAN mode (no internet needed, but phone and "
            "PC must reach each other — client-isolating wifi blocks it).")
        self.relay_edit.editingFinished.connect(self._restart_transport)
        relay_row.addWidget(self.relay_edit, 1)
        lay.addLayout(relay_row)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #98a2b3;")
        lay.addWidget(self.hint)
        self.status = QLabel("Waiting for a photo…")
        lay.addWidget(self.status)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._restart_transport()

    # -- transport lifecycle -------------------------------------------
    def _stop_transport(self):
        if self._server:
            self._server.stop()
            self._server = None
        if self._poller:
            self._poller.stop()
            self._poller = None

    def _restart_transport(self):
        text = self.relay_edit.text().strip()
        _settings().setValue("phone/relay_url", text)
        self._stop_transport()
        relay = "" if text.lower() in _LAN_WORDS else (text or DEFAULT_RELAY)
        if relay:
            token = photorelay.new_token()
            url = photorelay.page_url(relay, token)
            self._poller = photorelay.RelayPoller(
                relay, token, self.save_dir,
                on_photo=self._bridge.received.emit)
            self._poller.start()
            self.hint.setText(
                "Via your relay — works on any network, even mobile data.")
        else:
            self._server = PhotoShareServer(
                self.save_dir, on_photo=self._bridge.received.emit)
            url = self._server.start()
            self.hint.setText(
                "Direct LAN mode: phone and PC must be on the same network. "
                "On eduroam (client isolation) use the phone's hotspot — or "
                "set up the relay (relay/README.md) to work from anywhere.")
        self.qr_label.setPixmap(qr_pixmap(url))
        self.url_edit.setText(url)
        self.status.setText("Waiting for a photo…")

    # -- events --------------------------------------------------------
    def _on_received(self, path):
        self.photo_path = path
        self.status.setText("Photo received.")
        self.accept()

    def done(self, r):                      # any close path stops everything
        self._stop_transport()
        super().done(r)
