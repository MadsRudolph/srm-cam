"""EXPERIMENTAL SPI streaming: protocol behaviour on a fake serial."""
import pytest

from gerber2rml.engine.spi_stream import StreamError, stream_toolpaths
from gerber2rml.toolpath import Move


class StreamSerial:
    """Fake v2 board: acks C with an origin, echoes M moves; records them."""
    def __init__(self, fail_at=None):
        self._out = []
        self.moves = []            # (x, y, z, speed) um as received
        self.aborted = False
        self.fail_at = fail_at

    def write(self, data):
        s = data.decode().strip()
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
