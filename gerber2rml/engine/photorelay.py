"""Phone-to-GUI photo hand-off THROUGH the relay (relay/worker.js).

Used when the wifi blocks device-to-device traffic (eduroam): the phone
uploads to the relay at an unguessable token URL, and this poller pulls
the photo down to the workspace. The relay hands each photo over exactly
once and expires it after 10 minutes; the PC accepts no inbound traffic.
"""
from __future__ import annotations

import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/bmp": ".bmp"}


def new_token() -> str:
    return secrets.token_urlsafe(16)          # 128-bit, fits the relay regex


def page_url(relay: str, token: str) -> str:
    return f"{relay.rstrip('/')}/u/{token}"


class RelayPoller(threading.Thread):
    """Polls <relay>/f/<token> until the photo arrives (or stop() is
    called), saves it into save_dir, then fires on_photo(path) - from
    this thread, so bridge it to the GUI thread like the local server."""

    def __init__(self, relay: str, token: str, save_dir,
                 on_photo=None, interval: float = 2.0):
        super().__init__(daemon=True)
        self.fetch_url = f"{relay.rstrip('/')}/f/{token}"
        self.save_dir = Path(save_dir)
        self.on_photo = on_photo
        self.interval = interval
        self.received: str | None = None
        self.error: str | None = None
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def run(self):
        self.save_dir.mkdir(parents=True, exist_ok=True)
        # custom UA: Cloudflare bot protection 403s the default python UA
        req = urllib.request.Request(
            self.fetch_url, headers={"User-Agent": "SRM-CAM"})
        while not self._halt.is_set():
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = r.read()
                    ctype = (r.headers.get("Content-Type") or "").split(";")[0]
            except urllib.error.HTTPError as e:
                if e.code != 404:              # 404 = not uploaded yet
                    self.error = f"relay error {e.code}"
                self._halt.wait(self.interval)
                continue
            except OSError as e:               # DNS, refused, timeout, ...
                self.error = str(e)
                self._halt.wait(self.interval)
                continue
            if self._halt.is_set():            # stopped while fetching
                return
            if len(data) < 100:                # relay never stores < 100 B
                self._halt.wait(self.interval)
                continue
            ext = _EXT.get(ctype.strip().lower(), ".jpg")
            path = self.save_dir / time.strftime(f"phone_%Y%m%d_%H%M%S{ext}")
            path.write_bytes(data)
            self.received = str(path)
            self.error = None
            if self.on_photo:
                self.on_photo(str(path))
            return

