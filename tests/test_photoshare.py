"""Phone photo hand-off: the in-app upload server + QR dialog."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import urllib.error
import urllib.request

import pytest
from PySide6.QtWidgets import QApplication

from gerber2rml.engine.photoshare import MAX_BYTES, PhotoShareServer

_app = QApplication.instance() or QApplication([])

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 500          # fake-but-plausible payload


def _post(url, data, ctype="image/jpeg"):
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype})
    return urllib.request.urlopen(req, timeout=5)


@pytest.fixture
def server(tmp_path):
    got = []
    done = threading.Event()

    def on_photo(p):
        got.append(p)
        done.set()

    srv = PhotoShareServer(tmp_path / "photos", on_photo=on_photo)
    srv.start()
    srv._test_got = got
    srv._test_done = done
    yield srv
    srv.stop()


def _local(srv, path):
    return f"http://127.0.0.1:{srv.port}{path}"


def test_page_served_with_token(server):
    with urllib.request.urlopen(
            _local(server, f"/u/{server.token}"), timeout=5) as r:
        body = r.read().decode()
    assert r.status == 200
    assert "Take photo" in body
    assert f"/p/{server.token}" in body          # POST target wired in


def test_wrong_token_404(server):
    for path in ("/u/nope", "/", f"/p/nope"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(_local(server, path), timeout=5)
        assert e.value.code in (404, 501)


def test_upload_saves_and_notifies(server):
    with _post(_local(server, f"/p/{server.token}"), JPEG) as r:
        assert r.status == 200
    assert server._test_done.wait(5)
    (path,) = server._test_got
    assert path.endswith(".jpg")
    with open(path, "rb") as f:
        assert f.read() == JPEG
    assert server.received == path


def test_png_content_type_gets_png_extension(server):
    with _post(_local(server, f"/p/{server.token}"), JPEG, "image/png"):
        pass
    assert server._test_done.wait(5)
    assert server._test_got[0].endswith(".png")


def test_oversize_rejected(server):
    req = urllib.request.Request(
        _local(server, f"/p/{server.token}"), data=b"x", method="POST",
        headers={"Content-Type": "image/jpeg",
                 "Content-Length": str(MAX_BYTES + 1)})
    with pytest.raises(Exception):
        urllib.request.urlopen(req, timeout=5)
    assert not server._test_got


def test_url_contains_token_and_port(server):
    assert f"/u/{server.token}" in server.url
    assert f":{server.port}/" in server.url


def test_qr_pixmap_renders():
    from gerber2rml.gui.phonephoto import qr_pixmap
    pm = qr_pixmap("http://192.168.0.10:12345/u/abcdefgh")
    assert not pm.isNull()
    assert pm.width() > 100                      # real module grid, not empty


def test_dialog_accepts_on_photo(tmp_path):
    from PySide6.QtWidgets import QDialog
    from gerber2rml.gui.phonephoto import PhonePhotoDialog
    dlg = PhonePhotoDialog(None, tmp_path / "photos")
    try:
        assert dlg.photo_path is None
        with _post(f"http://127.0.0.1:{dlg._server.port}"
                   f"/p/{dlg._server.token}", JPEG):
            pass
        # the accept arrives via a queued signal; pump the event loop
        for _ in range(100):
            _app.processEvents()
            if dlg.photo_path:
                break
        assert dlg.photo_path and dlg.photo_path.endswith(".jpg")
        assert dlg.result() == QDialog.Accepted or dlg.photo_path
    finally:
        dlg._server.stop()
