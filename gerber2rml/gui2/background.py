"""Heavy sums off the GUI thread, newest answer only.

The laser page rebuilds its rings, its trench skips and its time estimate on
every edit. Each takes from a tenth of a second to several seconds on a big
board, and run on the GUI thread they froze the window for as long. Here they
run on Qt's thread pool and the answer comes back on the GUI thread.

Only the newest request under a name is delivered: if the ring count is
clicked from 6 to 3, three rebuilds start, and the first two are thrown away
when they finish. Nothing is cancelled mid-sum (Python cannot stop a thread),
so a request is also *debounced*: ``later()`` waits until the edits have
stopped for ``ms`` before it starts.

    bg = Latest(page)
    bg.run("rings", lambda: build(snapshot), done=page._take_rings)
    bg.later("estimate", 150, make_job, done=show_time)

``fn`` runs on a worker thread and must not touch a widget: it gets what it
needs by closure, taken on the GUI thread when the request was made. ``done``
and ``failed`` run on the GUI thread.

``INLINE = True`` runs every request at once on the calling thread; the test
suite does this, so a test sees the result the moment it makes the edit.
"""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

INLINE = False


class _Job(QRunnable):
    def __init__(self, fn, deliver):
        super().__init__()
        self._fn = fn
        self._deliver = deliver

    def run(self):
        try:
            result, error = self._fn(), None
        except Exception as e:              # noqa: BLE001 - handed to failed()
            result, error = None, e
        try:
            self._deliver(result, error)
        except RuntimeError:                # the page is gone: nobody to tell
            pass


class Latest(QObject):
    """Runs named requests on the thread pool; delivers only the newest."""

    _arrived = Signal(str, int, object, object)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gen = {}          # name -> number of the newest request
        self._calls = {}        # name -> (done, failed) of the newest request
        self._running = {}      # name -> requests still out
        self._timers = {}
        self._waiting = {}      # name -> (fn, done, failed) not yet started
        self._arrived.connect(self._deliver)

    # ------------------------------------------------------------ requests
    def run(self, name, fn, done=None, failed=None):
        """Start ``fn()`` now; ``done(result)`` once it is back, unless a
        newer ``name`` request has been made meanwhile."""
        t = self._timers.get(name)
        if t is not None:
            t.stop()
        self._waiting.pop(name, None)
        gen = self._gen.get(name, 0) + 1
        self._gen[name] = gen
        self._calls[name] = (done, failed)
        if INLINE:
            try:
                result, error = fn(), None
            except Exception as e:          # noqa: BLE001
                result, error = None, e
            self._deliver(name, gen, result, error)
            return
        was_busy = self.busy()
        self._running[name] = self._running.get(name, 0) + 1
        emit = self._arrived.emit
        QThreadPool.globalInstance().start(
            _Job(fn, lambda r, e: emit(name, gen, r, e)))
        if not was_busy:
            self.busy_changed.emit(True)

    def later(self, name, ms, fn, done=None, failed=None):
        """``run()`` once the requests under ``name`` have stopped for
        ``ms``. ``fn`` is the last one asked for."""
        if INLINE:
            return self.run(name, fn, done, failed)
        self._gen[name] = self._gen.get(name, 0) + 1   # a pending answer is stale
        self._waiting[name] = (fn, done, failed)
        t = self._timers.get(name)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda: self._fire(name))
            self._timers[name] = t
        t.start(ms)

    def _fire(self, name):
        req = self._waiting.pop(name, None)
        if req is not None:
            self.run(name, *req)

    def cancel(self, name):
        """Forget ``name``'s pending answer, if any."""
        t = self._timers.get(name)
        if t is not None:
            t.stop()
        self._waiting.pop(name, None)
        self._gen[name] = self._gen.get(name, 0) + 1

    def pending(self, name):
        """True while an answer under ``name`` is on its way."""
        t = self._timers.get(name)
        return bool(self._running.get(name)) or (t is not None and t.isActive())

    def busy(self):
        return any(self._running.values())

    def wait(self, timeout_ms=60000):
        """Block until every request is in and delivered (tests, closing)."""
        from PySide6.QtCore import QCoreApplication, QDeadlineTimer
        for name, t in list(self._timers.items()):
            if t.isActive():
                t.stop()
                self._fire(name)
        QThreadPool.globalInstance().waitForDone(timeout_ms)
        deadline = QDeadlineTimer(timeout_ms)
        while self.busy() and not deadline.hasExpired():
            QCoreApplication.processEvents()

    # ------------------------------------------------------------ answers
    def _deliver(self, name, gen, result, error):
        if not INLINE:
            self._running[name] = max(0, self._running.get(name, 0) - 1)
            if not self.busy():
                self.busy_changed.emit(False)
        if gen != self._gen.get(name):
            return                          # a newer request is out
        done, failed = self._calls.pop(name, (None, None))
        if error is not None:
            if failed is not None:
                failed(error)
            return
        if done is not None:
            done(result)
