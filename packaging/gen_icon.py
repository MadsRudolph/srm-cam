"""Generate the SRM-CAM app icon: copper PCB traces + pads on the app's dark
theme. Reproducible — rerun after tweaking, no binary-only assets in the repo.

    python packaging/gen_icon.py

Writes packaging/srm-cam.ico (multi-size, PNG-compressed entries) and
packaging/srm-cam-256.png (used as the window/taskbar icon at runtime).
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QImage, QPainter,
                           QPainterPath, QPen)

BG = QColor("#171b22")
EDGE = QColor("#2c333f")
COPPER = QColor("#d8893c")
COPPER_HI = QColor("#e8a45c")


def render(size=256):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0

    def S(v):
        return v * s

    # board: rounded dark square with a subtle edge
    path = QPainterPath()
    path.addRoundedRect(QRectF(S(10), S(10), S(236), S(236)), S(44), S(44))
    p.fillPath(path, QBrush(BG))
    p.setPen(QPen(EDGE, S(6)))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)

    # traces: classic 45-degree PCB routing
    pen = QPen(COPPER, S(22), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    tr1 = QPainterPath(QPointF(S(60), S(196)))
    tr1.lineTo(S(60), S(122))
    tr1.lineTo(S(126), S(56))
    tr1.lineTo(S(196), S(56))
    p.drawPath(tr1)
    tr2 = QPainterPath(QPointF(S(196), S(196)))
    tr2.lineTo(S(196), S(148))
    tr2.lineTo(S(142), S(94))
    p.drawPath(tr2)

    # pads (copper ring with a drilled hole) + a via on trace 2's end
    def pad(cx, cy, r, hole):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(COPPER_HI))
        p.drawEllipse(QPointF(S(cx), S(cy)), S(r), S(r))
        p.setBrush(QBrush(BG))
        p.drawEllipse(QPointF(S(cx), S(cy)), S(hole), S(hole))

    pad(60, 196, 30, 12)
    pad(196, 56, 30, 12)
    pad(196, 196, 30, 12)
    pad(142, 94, 17, 7)
    p.end()
    return img


def qimage_png_bytes(img):
    from PySide6.QtCore import QBuffer, QByteArray
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Multi-size .ico with PNG-compressed entries (valid since Vista)."""
    base = render(256)
    entries = []
    for sz in sizes:
        img = base if sz == 256 else base.scaled(
            sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        entries.append((sz, qimage_png_bytes(img)))
    header = struct.pack("<HHH", 0, 1, len(entries))
    dir_size = 16 * len(entries)
    offset = len(header) + dir_size
    directory = b""
    blobs = b""
    for sz, png in entries:
        b = 0 if sz == 256 else sz
        directory += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32,
                                 len(png), offset)
        blobs += png
        offset += len(png)
    Path(path).write_bytes(header + directory + blobs)


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    here = Path(__file__).parent
    write_ico(here / "srm-cam.ico")
    render(256).save(str(here / "srm-cam-256.png"))
    print("wrote", here / "srm-cam.ico", "and srm-cam-256.png")
