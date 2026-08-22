"""EXPERIMENTAL SPI streaming: protocol behaviour on a fake serial."""
import pytest

from gerber2rml.engine.spi_stream import StreamError, stream_toolpaths
from gerber2rml.toolpath import Move


# The idle word observed on the real machine in the 2026-08 audit. NOT zero:
# an all-zero (or all-ones) system word is what a FAILED SPI transfer looks
# like, and both machine_status and the stream's cover watch treat it as
# "I could not read that" rather than a healthy, lid-shut machine.
IDLE_SYSTEM = 0x01000082
COVER_BIT = 0x20000
SPINDLE_BIT = 0x10000


class StreamSerial:
    """Fake v2 board: acks C with an origin, echoes M moves; records them."""
    def __init__(self, fail_at=None):
        self._out = []
        self.moves = []            # (x, y, z, speed) um as received
        self.aborted = False
        self.fail_at = fail_at
        self.status_reads = 0

    def write(self, data):
        s = data.decode().strip()
        if s == "X":
            self.status_reads += 1
            self._out.append(f"X {IDLE_SYSTEM} 4 0\n".encode())
            return
        if s == "C":
            self._out.append(b"C 120000 26000 -54260\n")
        elif s.startswith("M"):
            _, x, y, z, sp = s.split()
            if self.fail_at is not None and len(self.moves) >= self.fail_at:
                self._out.append(b"E M ABORT\n")
                return
            self.moves.append((int(x), int(y), int(z), int(sp)))
            self._out.append(f"M {x} {y} {z}\n".encode())
        elif s == "!":
            self.aborted = True

    def readline(self):
        return self._out.pop(0) if self._out else b""

    def close(self):
        pass


def _job():
    return [[Move(0, 0, 2.0, rapid=True), Move(0, 0, -0.15),
             Move(10, 0, -0.15), Move(10, 0, 2.0, rapid=True)],
            [Move(20, 5, 2.0, rapid=True), Move(20, 5, -0.15)]]


def test_dry_run_clamps_all_z_high():
    s = StreamSerial()
    n = stream_toolpaths(s, _job(), dry_run=True, dry_lift_mm=2.0)
    assert n == 6 and len(s.moves) == 6
    assert all(z == 2000 for (_x, _y, z, _sp) in s.moves)   # nothing can cut
    assert s.moves[2][:2] == (10000, 0)                     # XY still traced


def test_wet_run_sends_real_z_and_speed():
    s = StreamSerial()
    stream_toolpaths(s, _job(), dry_run=False, speed=7)
    assert s.moves[1][2] == -150                            # cut depth reached
    assert all(sp == 7 for (_x, _y, _z, sp) in s.moves)


def test_move_failure_aborts_and_raises():
    s = StreamSerial(fail_at=3)
    with pytest.raises(StreamError):
        stream_toolpaths(s, _job(), dry_run=True)
    assert s.aborted                                        # tool was lifted


def test_operator_abort_lifts_and_raises():
    s = StreamSerial()
    calls = {"n": 0}

    def abort():
        calls["n"] += 1
        return calls["n"] > 4

    with pytest.raises(StreamError):
        stream_toolpaths(s, _job(), dry_run=True, should_abort=abort)
    assert s.aborted


def test_v1_firmware_refused():
    class V1Serial(StreamSerial):
        def write(self, data):
            pass                                            # ignores 'C'

    with pytest.raises(StreamError):
        stream_toolpaths(V1Serial(), _job())


# --- v3: spindle, pause and the cover watch -------------------------------
# Everything below drives an SPI command proven on the machine in the 2026-08
# audit. The spindle one matters most: a wet run now starts and stops the tool
# itself, so getting the "stop it whatever happens" path wrong is the bug that
# would leave a bit spinning.

class V3Serial(StreamSerial):
    """Fake board that also answers X (status) and S (spindle)."""

    def __init__(self, cover=False, spindle_starts=True, **kw):
        super().__init__(**kw)
        self.cover = cover
        self.spindle_starts = spindle_starts
        self.spindle = False
        self.spindle_cmds = []
        self.jobctl = []

    def write(self, data):
        s = data.decode().strip()
        if s == "X":
            self.status_reads += 1
            sys_word = (IDLE_SYSTEM
                        | (COVER_BIT if self.cover else 0)
                        | (SPINDLE_BIT if self.spindle else 0))
            self._out.append(f"X {sys_word} 4 {8600 if self.spindle else 0}\n".encode())
            return
        if s.startswith("S"):
            rpm = int(s[1:])
            self.spindle_cmds.append(rpm)
            if rpm and self.spindle_starts:
                self.spindle = True
            elif not rpm:
                self.spindle = False
            self._out.append(f"S {rpm}\n".encode())
            return
        if s in ("~", "^"):
            self.jobctl.append(s)
            self._out.append(f"{s} ok\n".encode())
            return
        if s == "%":
            self._out.append(b"% ok\n")
            return
        super().write(data)

    def reset_input_buffer(self):
        self._out.clear()


def test_wet_run_starts_and_stops_the_spindle():
    s = V3Serial()
    stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000)
    assert s.spindle_cmds[0] == 3000        # started before the first move
    assert s.spindle_cmds[-1] == 0          # and stopped at the end
    assert not s.spindle


def test_dry_run_never_spins_the_tool():
    s = V3Serial()
    stream_toolpaths(s, _job(), dry_run=True, spindle_rpm=3000)
    assert s.spindle_cmds == []             # a dry run cuts nothing, so no spindle


def test_spindle_is_stopped_even_when_the_run_fails():
    """The finally-path that keeps a bit from spinning after a crash."""
    s = V3Serial(fail_at=2)
    with pytest.raises(StreamError):
        stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000)
    assert s.spindle_cmds[-1] == 0
    assert not s.spindle


def test_wet_run_refuses_to_start_with_the_lid_open():
    s = V3Serial(cover=True)
    with pytest.raises(StreamError, match="lid open"):
        stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000)
    assert s.spindle_cmds == []             # never even asked


def test_wet_run_stops_if_the_spindle_never_reports_running():
    s = V3Serial(spindle_starts=False)
    with pytest.raises(StreamError, match="never reported running"):
        stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000)
    assert s.moves == []                    # nothing touched the work
    assert s.spindle_cmds[-1] == 0          # and it was told to stop


def test_pause_holds_the_run_then_resumes():
    s = V3Serial()
    state = {"n": 0}

    def should_pause():
        state["n"] += 1
        return 3 <= state["n"] <= 5         # paused for a few polls, then not

    n = stream_toolpaths(s, _job(), dry_run=True, should_pause=should_pause)
    assert n == 6                           # the job still completed
    assert s.jobctl == ["~", "^"]           # held once, released once


def test_lid_opening_mid_run_stops_and_lifts():
    long_job = [[Move(i, 0, 2.0) for i in range(40)]]
    s = V3Serial()

    def open_lid(i, _n):
        if i >= 20:
            s.cover = True

    with pytest.raises(StreamError, match="lid opened"):
        stream_toolpaths(s, long_job, dry_run=True, on_progress=open_lid)
    assert s.aborted


# --- the deadman, the short job, and the blind read ------------------------
# All three are ways the machine could keep cutting while the app believed it
# had things under control.

def test_a_held_pause_keeps_talking_to_the_board(monkeypatch):
    """The firmware stops a spindle it started if the host goes quiet for 10 s.
    A held pause IS silence, so the pause loop has to keep the link busy or the
    operator's own Pause kills the tool mid-cut."""
    from gerber2rml.engine import spi_stream
    monkeypatch.setattr(spi_stream, "PAUSE_KEEPALIVE_S", 0.0)
    s = V3Serial()
    held = {"n": 0}

    def should_pause():
        held["n"] += 1
        return held["n"] < 8        # hold for a few loop turns, then release

    before = s.status_reads
    stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000,
                     should_pause=should_pause)
    assert s.status_reads > before, "the pause loop never spoke to the board"


def test_resume_refuses_if_the_spindle_died_during_the_pause(monkeypatch):
    """If the deadman (or anything else) stopped the tool while we were held,
    resuming would feed a stationary bit into copper."""
    from gerber2rml.engine import spi_stream
    monkeypatch.setattr(spi_stream, "PAUSE_KEEPALIVE_S", 0.0)
    s = V3Serial()
    held = {"n": 0}

    def should_pause():
        held["n"] += 1
        if held["n"] == 3:
            s.spindle = False       # the deadman fires while we are held
        return held["n"] < 6

    with pytest.raises(StreamError, match="spindle stopped"):
        stream_toolpaths(s, _job(), dry_run=False, spindle_rpm=3000,
                         should_pause=should_pause)
    assert s.aborted


def test_short_job_with_the_lid_open_never_starts():
    """_job() is 6 moves. The old poll fired on `i % 20 == 19`, so a job this
    short was never checked at all."""
    s = V3Serial(cover=True)
    with pytest.raises(StreamError, match="lid"):
        stream_toolpaths(s, _job(), dry_run=True)
    assert not s.moves, "streamed into an open lid"


def test_lid_is_polled_by_move_count_not_only_by_clock():
    """The guarantee is: checked before the first move, then at least once a
    second AND at least every COVER_POLL_MOVES moves. This exercises the move
    counter - the whole job runs in well under the one-second clock, so only
    the count can catch it."""
    from gerber2rml.engine.spi_stream import COVER_POLL_MOVES
    job = [[Move(i, 0, 2.0) for i in range(COVER_POLL_MOVES + 4)]]
    s = V3Serial()

    def open_lid(i, _n):
        if i >= 2:
            s.cover = True

    with pytest.raises(StreamError, match="lid opened"):
        stream_toolpaths(s, job, dry_run=True, on_progress=open_lid)
    assert s.aborted


def test_an_unreadable_status_word_stops_the_run():
    """An all-zero word is a failed SPI transfer, not a shut lid. Cutting on
    the assumption that no news is good news is how the cover watch silently
    stops working."""
    class Blind(V3Serial):
        def write(self, data):
            if data.decode().strip() == "X":
                self.status_reads += 1
                self._out.append(b"X 0 0 0\n")
                return
            super().write(data)

    s = Blind()
    with pytest.raises(StreamError, match="status word"):
        stream_toolpaths(s, [[Move(i, 0, 2.0) for i in range(60)]], dry_run=True)
    assert s.aborted
