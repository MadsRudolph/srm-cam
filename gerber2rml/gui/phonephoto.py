"""Phone hand-off dialog: QR code -> phone camera page -> photo lands here.

Wraps engine.photoshare.PhotoShareServer in a modal dialog: shows the QR
(and the URL as text fallback), waits, and accepts as soon as one photo has
been uploaded. ``photo_path`` then holds the saved file.
"""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                               QVBoxLayout)

from gerber2rml.engine.photoshare import PhotoShareServer


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
    # emitted from the HTTP server thread; auto-queued to the GUI thread
    received = Signal(str)


class PhonePhotoDialog(QDialog):
    def __init__(self, parent, save_dir):
        super().__init__(parent)
        self.setWindowTitle("Photo from phone")
        self.photo_path = None
        self._bridge = _Bridge()
        self._bridge.received.connect(self._on_received)
        self._server = PhotoShareServer(
            save_dir, on_photo=self._bridge.received.emit)
        url = self._server.start()

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        head = QLabel("Scan with the phone camera, then take the photo:")
        head.setWordWrap(True)
        lay.addWidget(head)
        qr = QLabel()
        qr.setPixmap(qr_pixmap(url))
        qr.setAlignment(Qt.AlignCenter)
        lay.addWidget(qr)
        self.url_edit = QLineEdit(url)
        self.url_edit.setReadOnly(True)
        self.url_edit.setToolTip("Or type this address in the phone browser.")
        lay.addWidget(self.url_edit)
        hint = QLabel(
            "Phone and PC must be on the same network. On eduroam (client "
            "isolation) connect the PC to the phone's hotspot instead.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #98a2b3;")
        lay.addWidget(hint)
        self.status = QLabel("Waiting for a photo…")
        lay.addWidget(self.status)
        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _on_received(self, path):
        self.photo_path = path
        self.status.setText("Photo received.")
        self.accept()

    def done(self, r):                      # any close path stops the server
        self._server.stop()
        super().done(r)
