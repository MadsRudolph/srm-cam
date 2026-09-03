"""Phone-to-GUI photo hand-off: a tiny in-app HTTP server + QR code.

The GUI shows a QR code for ``http://<lan-ip>:<port>/u/<token>``; the phone's
camera app opens that page, which is a single "take photo" button. The photo
POSTs straight back (raw bytes, no multipart) and lands in the workspace
photos folder; the GUI is told via callback and opens the anchor dialog.

No cloud, no accounts. The random URL token is the access control: the server
answers 404 to everything else, accepts exactly ONE photo per session, and
lives only while the dialog is open. Note: eduroam-style networks isolate
clients — the phone hotspot is the reliable fallback there.
"""
from __future__ import annotations

import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BYTES = 40 * 1024 * 1024          # phone photos are ~2-12 MB; 40 is generous

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/bmp": ".bmp"}

# Self-contained mobile page. accept+capture opens the camera directly on
# phones; the file POSTs as a raw body (fetch) so the server needs no
# multipart parsing. Dark-themed to match the app.
_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SRM-CAM photo</title><style>
body{background:#171b22;color:#d7dde6;font-family:system-ui,sans-serif;
 display:flex;flex-direction:column;align-items:center;justify-content:center;
 min-height:100vh;margin:0;gap:24px;text-align:center}
h1{font-size:1.2rem;margin:0}
label{background:#d8893c;color:#16120c;font-weight:700;font-size:1.2rem;
 padding:20px 44px;border-radius:14px;cursor:pointer}
input{display:none}#st{color:#98a2b3;min-height:1.4em;padding:0 20px}
.ok{color:#4fc07a;font-weight:700}.err{color:#e06555}</style></head><body>
<h1>SRM-CAM &mdash; board photo</h1>
<label for="f">&#128247; Take photo</label>
<input id="f" type="file" accept="image/*" capture="environment">
<div id="st">Straight down, even light, no glare.</div>
<script>
const f=document.getElementById('f'),st=document.getElementById('st');
f.addEventListener('change',async()=>{
 if(!f.files.length)return;
 st.textContent='Uploading\\u2026';st.className='';
 try{
  const r=await fetch('%POST%',{method:'POST',body:f.files[0],
   headers:{'Content-Type':f.files[0].type||'image/jpeg'}});
  if(r.ok){st.textContent='\\u2713 Received \\u2014 continue on the PC';
   st.className='ok';document.querySelector('label').style.display='none';}
  else{st.textContent='Upload failed ('+r.status+') \\u2014 try again';
   st.className='err';}
 }catch(e){st.textContent='Upload failed \\u2014 same network as the PC? '+
  'On eduroam use the phone hotspot.';st.className='err';}
});
</script></body></html>"""


def lan_ip() -> str:
    """Best-guess LAN IPv4 of this machine (no packets actually sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


class _Server(ThreadingHTTPServer):
    # Closing must not wait for a phone that is still uploading: stop() runs
    # on the GUI thread, and block_on_close joins every handler thread.
    daemon_threads = True
    block_on_close = False


class PhotoShareServer:
    """One-shot photo receiver. start() -> .url for the QR; on_photo(path)
    fires (from a server thread!) when a photo has been saved; stop() always.
    """

    def __init__(self, save_dir, on_photo=None):
        self.save_dir = Path(save_dir)
        self.on_photo = on_photo
        self.token = secrets.token_urlsafe(8)
        self._httpd = None
        self._thread = None
        self.received: str | None = None

    # -- lifecycle -----------------------------------------------------
    def start(self) -> str:
        self.save_dir.mkdir(parents=True, exist_ok=True)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # keep the GUI console quiet
                pass

            def _deny(self):
                self.send_error(404)

            def do_GET(self):
                if self.path != f"/u/{owner.token}":
                    return self._deny()
                body = _PAGE.replace("%POST%", f"/p/{owner.token}")
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if self.path != f"/p/{owner.token}":
                    return self._deny()
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    n = 0
                if n <= 0 or n > MAX_BYTES:
                    return self.send_error(413)
                data = self.rfile.read(n)
                ctype = (self.headers.get("Content-Type") or "").split(";")[0]
                ext = _EXT.get(ctype.strip().lower(), ".jpg")
                path = owner.save_dir / time.strftime(
                    f"phone_%Y%m%d_%H%M%S{ext}")
                path.write_bytes(data)
                owner.received = str(path)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
                if owner.on_photo:
                    owner.on_photo(str(path))

        self._httpd = _Server(("0.0.0.0", 0), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else 0

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/u/{self.token}"

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
