"""Relay transport: poller + dialog against a local fake of relay/worker.js."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtWidgets import QApplication

from gerber2rml.engine.photorelay import RelayPoller, new_token, page_url

_app = QApplication.instance() or QApplication([])

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 500


class FakeRelay:
    """Local stand-in for the Cloudflare worker: /f/<token> 404s until a
    photo is 'uploaded', then serves it once and deletes it."""

    def __init__(self):
        self.store = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/f/"):
                    tok = self.path[3:]
                    data = outer.store.pop(tok, None)
                    if data is None:
                        return self.send_error(404)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_error(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_token_and_page_url():
    tok = new_token()
    assert len(tok) >= 12
    assert page_url("https://x.workers.dev/", tok) == \
        f"https://x.workers.dev/u/{tok}"


def test_poller_waits_then_fetches_once(tmp_path):
    relay = FakeRelay()
    try:
        tok = new_token()
        got = []
        done = threading.Event()
        p = RelayPoller(relay.url, tok, tmp_path / "photos",
                        on_photo=lambda x: (got.append(x), done.set()),
                        interval=0.05)
        p.start()
        time.sleep(0.2)                      # a few 404 polls first
        assert not got
        relay.store[tok] = JPEG              # phone "uploads"
        assert done.wait(5)
        (path,) = got
        with open(path, "rb") as f:
            assert f.read() == JPEG
        assert tok not in relay.store        # one-shot: relay copy consumed
    finally:
        relay.stop()


def test_poller_survives_dead_relay_then_stop(tmp_path):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()                                # nothing listens -> refused fast
    p = RelayPoller(f"http://127.0.0.1:{dead_port}", new_token(), tmp_path,
                    interval=0.05)
    p.start()
    for _ in range(100):                     # first attempt may take a moment
        if p.error:
            break
        time.sleep(0.05)
    assert p.is_alive() and p.error          # erroring but not crashed
    p.stop()
    p.join(2)
    assert not p.is_alive()


def test_dialog_relay_mode(tmp_path):
    from gerber2rml.gui.phonephoto import PhonePhotoDialog
    from gerber2rml.gui.workspace import _settings
    relay = FakeRelay()
    try:
        _settings().setValue("phone/relay_url", relay.url)
        dlg = PhonePhotoDialog(None, tmp_path / "photos")
        try:
            assert dlg._poller is not None and dlg._server is None
            assert relay.url in dlg.url_edit.text()
            tok = dlg.url_edit.text().rsplit("/", 1)[1]
            relay.store[tok] = JPEG
            for _ in range(200):
                _app.processEvents()
                if dlg.photo_path:
                    break
                time.sleep(0.02)
            assert dlg.photo_path and dlg.photo_path.endswith(".jpg")
        finally:
            dlg._stop_transport()
    finally:
        _settings().setValue("phone/relay_url", "")
        relay.stop()


def test_dialog_empty_field_uses_default_relay(tmp_path):
    from gerber2rml.gui.phonephoto import DEFAULT_RELAY, PhonePhotoDialog
    from gerber2rml.gui.workspace import _settings
    _settings().setValue("phone/relay_url", "")
    dlg = PhonePhotoDialog(None, tmp_path / "photos")
    try:
        assert dlg._poller is not None and dlg._server is None
        assert dlg.url_edit.text().startswith(DEFAULT_RELAY + "/u/")
    finally:
        dlg._stop_transport()


def test_dialog_lan_keyword_gives_local_mode(tmp_path):
    from gerber2rml.gui.phonephoto import PhonePhotoDialog
    from gerber2rml.gui.workspace import _settings
    _settings().setValue("phone/relay_url", "lan")
    try:
        dlg = PhonePhotoDialog(None, tmp_path / "photos")
        try:
            assert dlg._server is not None and dlg._poller is None
            assert "/u/" in dlg.url_edit.text()
        finally:
            dlg._stop_transport()
    finally:
        _settings().setValue("phone/relay_url", "")
