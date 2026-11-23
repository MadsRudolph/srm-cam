"""A picture of a board from its Gerber folder, for the Project page: which
board is which when a dozen lie on the bench (2026-11-23, the analog synth).

gerbonara draws the whole stack - copper, mask, silkscreen, outline, holes -
as the board will look (``LayerStack.to_pretty_svg``), about a second for the
busiest of the synth's boards. That runs off the GUI thread; the SVG is kept
per folder and face until a file in the folder changes.
"""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from gerber2rml.gui2 import theme, widgets

_cache = {}                     # (folder, side, stamp) -> svg bytes, or an error str
_lock = threading.Lock()


def _stamp(folder):
    """Changes when any file in ``folder`` does."""
    try:
        return tuple(sorted((p.name, p.stat().st_mtime_ns)
                            for p in Path(folder).iterdir() if p.is_file()))
    except OSError:
        return ()


def render_svg(folder, side="top"):
    """The board in ``folder`` seen from ``side`` as SVG bytes. Raises
    ValueError, in words, when the folder holds no board."""
    from gerbonara import LayerStack
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"The folder is not there: {folder}")
    key = (str(folder), side, _stamp(folder))
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        if isinstance(hit, str):
            raise ValueError(hit)
        return hit
    try:
        stack = LayerStack.open(folder)
        svg = str(stack.to_pretty_svg(side=side)).encode("utf-8")
    except Exception as e:                      # noqa: BLE001 - said on the page
        msg = f"No picture of this board: {e}"
        with _lock:
            _cache[key] = msg
        raise ValueError(msg) from e
    with _lock:
        _cache[key] = svg
    return svg


class _Done(QObject):
    ready = Signal(str, str, object)            # folder, side, bytes or error str


class _Canvas(QWidget):
    """The SVG, as large as fits, its own shape kept."""

    def __init__(self):
        super().__init__()
        self._svg = None
        self.setMinimumSize(QSize(220, 160))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_svg(self, data):
        self._svg = QSvgRenderer(data) if data else None
        if self._svg is not None and not self._svg.isValid():
            self._svg = None
        self.update()

    def has_picture(self):
        return self._svg is not None

    def paintEvent(self, _e):
        if self._svg is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        vb = self._svg.viewBoxF()
        w, h = (vb.width(), vb.height()) if vb.width() > 0 else (4, 3)
        k = min(self.width() / w, self.height() / h)
        dw, dh = w * k, h * k
        self._svg.render(p, QRectF((self.width() - dw) / 2,
                                   (self.height() - dh) / 2, dw, dh))
        p.end()


class BoardPreview(QWidget):
    """The chosen board's picture, top or bottom."""

    def __init__(self):
        super().__init__()
        self._folder = None
        self._side = "top"
        self._done = _Done()
        self._done.ready.connect(self._arrived)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.GAP_S)
        head = QHBoxLayout()
        self.name = QLabel("")
        self.name.setFont(theme.font("sub"))
        head.addWidget(self.name, 1)
        self.top_btn = widgets.button("Top", kind="ghost",
                                      on=lambda: self.show_side("top"))
        self.bottom_btn = widgets.button("Bottom", kind="ghost",
                                         on=lambda: self.show_side("bottom"))
        for b in (self.top_btn, self.bottom_btn):
            b.setCheckable(True)
            head.addWidget(b)
        v.addLayout(head)
        self.canvas = _Canvas()
        v.addWidget(self.canvas, 1)
        self.note = widgets.hint("Choose a board to see it.")
        self.note.setAlignment(Qt.AlignCenter)
        v.addWidget(self.note)
        self._sync_buttons()

    def _sync_buttons(self):
        self.top_btn.setChecked(self._side == "top")
        self.bottom_btn.setChecked(self._side == "bottom")
        for b in (self.top_btn, self.bottom_btn):
            b.setEnabled(self._folder is not None)

    def show_board(self, name, folder):
        """``folder`` (or None) on the page, the face as it was."""
        self.name.setText(name or "")
        self._folder = str(folder) if folder else None
        self._load()

    def show_side(self, side):
        self._side = side
        self._load()

    def _load(self):
        self._sync_buttons()
        self.canvas.set_svg(None)
        if self._folder is None:
            self.note.setText("Choose a board to see it.")
            self.note.setVisible(True)
            return
        self.note.setText("Drawing the board…")
        self.note.setVisible(True)
        folder, side, done = self._folder, self._side, self._done

        def work():
            try:
                out = render_svg(folder, side)
            except Exception as e:              # noqa: BLE001 - said on the page
                out = str(e)
            done.ready.emit(folder, side, out)
        threading.Thread(target=work, daemon=True).start()

    def _arrived(self, folder, side, out):
        if folder != self._folder or side != self._side:
            return                              # another board was chosen since
        if isinstance(out, str):
            self.note.setText(out)
            self.note.setVisible(True)
            return
        self.canvas.set_svg(out)
        self.note.setText("Top: as it lies face up" if side == "top"
                          else "Bottom: turned over, as you look at it")
        self.note.setVisible(True)
