"""The mill's settings over USB control transfers (engine/millsetup.py).

Every byte here is from the USBPcap captures of VPanel 1.10 talking to the
lab SRM-20 on 2026-11-15 (docs/vpanel-settings.md names the file each came
from). The fake mill is a register file that answers the four transfers the
way the real one did, and keeps a log, so a test can say both what the mill
ended up holding and exactly what was put on the wire to get there.
"""
import pytest

from gerber2rml.engine import millsetup
from gerber2rml.engine.millsetup import SetupError

H = bytes.fromhex

# tomgang.pcapng: one poll, the head at machine 101.6, 152.4, 0.
IDLE = H("82 00 00 01 00 00 00 30 e0 8c 01 00 50 53 02 00 00 00 00 00"
         " 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 64 64"
         " 64 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00")
# spindel lav.pcapng: the spindle running with the slider at 16 %.
SPINNING = H("82 00 01 01 00 00 00 30 be a4 01 00 36 40 02 00 aa fb ff ff"
             " 00 00 00 00 00 00 00 00 00 00 00 00 d3 10 00 00 00 00 64 64"
             " 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00")
# jog.pcapng: the header's second byte is 09 for as long as the head moves.
JOGGING = IDLE[:1] + b"\x09" + IDLE[2:]


class FakeMill:
    """An SRM-20's settings channel: registers, a header, a live block."""

    def __init__(self, live=IDLE, lag=0, slow=0, flag=0):
        self.reg = {
            0x3100: H("01"),                          # NC Code
            0x3200: H("00 00 00"),
            0x3203: H("00 00 00 00 00 00 00 00 a8 26 ff ff"
                      " 00 00 00 00 00 00 00 00 00 00 00 00"),
            0x025B: H("00 00 00 00 00 00 00 00 ac 13 ff ff 00 00 00 00"
                      " 00 00 00 00 00 00 00 00 c0 19 03 00 50 53 02 00"
                      " 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"),
            0x3003: H("d0 07 00 00 58 1b 00 00"),
        }
        self.live = bytearray(live)
        self.lag = lag               # polls that still show the old percent
        self.slow = slow             # headers that say "not ready yet" first
        self.flag = flag             # bits the fifth byte carries all along
        self._unready = 0
        self.sent = []               # (register, value) of every request
        self._answer = b""
        self._saving = 0
        self._stale = 0
        self._was = None

    def ctrl_transfer(self, rtype, request, value, index, payload):
        assert request == 0x01 and index == 0
        if rtype == 0x41:
            data = bytes(payload)
            reg = (data[1] << 8) | data[2]
            # The register is on the wire twice, and must agree.
            assert data[0] == 0x01 and data[3] == 0x00 and reg == value
            self.sent.append((reg, data[4:]))
            self._unready = self.slow
            if data[4:]:
                self._write(reg, data[4:])
                self._answer = b""
            else:
                self._answer = self.reg.get(reg, b"")
            return len(data)
        assert rtype == 0xC1
        if value == 0x0002:
            return H("01 00 34 12")
        if value == 0x0001:
            if self._unready:
                # Straight down the cable: 20 or 40 and no length, for a
                # few milliseconds after every request.
                self._unready -= 1
                return bytes([0x82, self.live[1], self.live[2], 0x01,
                              0x40 if self._unready % 2 else 0x20, 0, 0, 0])
            saving, self._saving = self._saving, 0
            return bytes([0x82, self.live[1], self.live[2], 0x01,
                          (0x20 if saving else 0) | self.flag, 0, 0,
                          len(self._answer)])
        if value == 0x0003:
            assert payload >= max(len(self._answer), 3)
            return self._answer
        if value == 0x0100:
            assert payload == 56
            out = bytes(self.live)
            if self._stale:
                self._stale -= 1
                out = out[:40] + bytes([self._was]) + out[41:]
            return out
        raise AssertionError(f"unknown transfer {rtype:#x} {value:#x}")

    def _write(self, reg, value):
        self._saving = 1
        if reg == 0x3101:
            self.reg[0x3100] = value
        elif reg == 0x3201:
            self.reg[0x3200] = value
        elif reg == 0x3006:
            self._was, self._stale = self.live[40], self.lag
            self.live[40] = value[0]
        else:
            raise AssertionError(f"a write to {reg:#06x} was never captured")

    def writes(self):
        return [(r, v) for r, v in self.sent if v]


FAST = {"sleep": lambda _s: None}


def test_the_request_bytes_are_the_ones_vpanel_sent():
    """opstart.pcapng: ``41 01 03 30 00 00 04 00`` with data ``01 30 03 00``."""
    seen = []

    class Wire(FakeMill):
        def ctrl_transfer(self, rtype, request, value, index, payload):
            seen.append((rtype, request, value, index,
                         bytes(payload) if rtype == 0x41 else payload))
            return super().ctrl_transfer(rtype, request, value, index, payload)

    assert millsetup.read_register(Wire(), 0x3003) == H(
        "d0 07 00 00 58 1b 00 00")
    assert seen == [(0x41, 1, 0x3003, 0, H("01 30 03 00")),
                    (0xC1, 1, 0x0001, 0, 8),
                    (0xC1, 1, 0x0003, 0, 8)]


def test_a_one_byte_answer_is_asked_for_as_three_like_vpanel():
    seen = []

    class Wire(FakeMill):
        def ctrl_transfer(self, rtype, request, value, index, payload):
            if value == 0x0003:
                seen.append(payload)
            return super().ctrl_transfer(rtype, request, value, index, payload)

    assert millsetup.read_register(Wire(), 0x3100) == H("01")
    assert seen == [3]


def test_an_answer_that_is_not_ready_yet_is_waited_for():
    """Seen on the lab mill without a network link in between: the first
    header after a request says 20 or 40 and announces nothing. Reading on
    regardless gave "the mill sent 0 bytes where 12 were expected"."""
    mill = FakeMill(slow=3)
    assert millsetup.g54_origin(mill, ) == (0.0, 0.0, -55.64)
    assert millsetup.command_set(mill) == "nc"
    assert millsetup.set_command_set(mill, nc=False, **FAST) == "rml"


def test_a_mill_that_is_only_moving_is_not_taken_for_busy():
    """The fifth byte read 04 for as long as a run was moving the head, with
    the answer waiting. Waiting for 00 gave "the mill took the request but
    stayed busy" - and "the mill's settings could not be read" on screen,
    with the mill switched on (the lab mill, 2026-11-15)."""
    mill = FakeMill(flag=0x04)
    assert millsetup.command_set(mill) == "nc"
    assert millsetup.g54_origin(mill) == (0.0, 0.0, -55.64)
    assert millsetup.set_spindle_percent(mill, 60, **FAST) == 60


def test_a_header_asked_before_the_mill_has_begun_is_asked_again():
    """Idle and empty is what the header says before the request has been
    looked at. That is not "no answer"."""
    class Late(FakeMill):
        def __init__(self):
            super().__init__()
            self.early = 0

        def ctrl_transfer(self, rtype, request, value, index, payload):
            if rtype == 0x41:
                self.early = 2
            if rtype == 0xC1 and value == 0x0001 and self.early:
                self.early -= 1
                return bytes([0x82, 0, 0, 0x01, 0, 0, 0, 0])
            return super().ctrl_transfer(rtype, request, value, index, payload)

    assert millsetup.command_set(Late()) == "nc"


def test_status_reads_position_and_the_sliders():
    st = millsetup.status(FakeMill())
    assert (st["x_mm"], st["y_mm"], st["z_mm"]) == (101.6, 152.4, 0.0)
    assert not st["busy"] and not st["spindle_on"]
    assert (st["speed_percent"], st["spindle_percent"]) == (100, 100)


def test_status_while_the_spindle_runs_at_sixteen_percent():
    st = millsetup.status(FakeMill(SPINNING))
    assert st["spindle_on"] and st["spindle_percent"] == 16
    assert st["spindle_reading"] == 4307
    assert st["z_mm"] == -1.11


def test_command_set_reads_nc_and_rml():
    mill = FakeMill()
    assert millsetup.command_set(mill) == "nc"
    mill.reg[0x3100] = H("00")
    assert millsetup.command_set(mill) == "rml"


def test_setting_rml_sends_what_vpanel_sent_on_ok():
    """command-set-nc-rml-nc.pcapng, 11.8 s: ``3101 <- 00`` then
    ``3201 <- 00 00 00``, and Setup read 00 the next time it opened."""
    mill = FakeMill()
    assert millsetup.set_command_set(mill, nc=False, **FAST) == "rml"
    assert mill.writes() == [(0x3101, H("00")), (0x3201, H("00 00 00"))]


def test_setting_nc_sends_what_vpanel_sent_on_ok():
    """The same capture, 20.8 s: ``3101 <- 01``."""
    mill = FakeMill()
    mill.reg[0x3100] = H("00")
    assert millsetup.set_command_set(mill, nc=True, **FAST) == "nc"
    assert mill.writes() == [(0x3101, H("01")), (0x3201, H("00 00 00"))]


def test_the_rest_of_the_setup_dialog_goes_back_exactly_as_read():
    mill = FakeMill()
    mill.reg[0x3200] = H("01 00 02")
    millsetup.set_command_set(mill, nc=False, **FAST)
    assert mill.writes()[1] == (0x3201, H("01 00 02"))
    assert mill.reg[0x3200] == H("01 00 02")


def test_a_mill_already_in_the_wanted_set_is_not_written_to():
    mill = FakeMill()
    assert millsetup.set_command_set(mill, nc=True, **FAST) == "nc"
    assert mill.writes() == []


@pytest.mark.parametrize("live", [JOGGING, SPINNING])
def test_the_command_set_is_not_changed_under_a_moving_mill(live):
    mill = FakeMill(live)
    with pytest.raises(SetupError, match="stands still"):
        millsetup.set_command_set(mill, nc=False, **FAST)
    assert mill.writes() == []


def test_a_mill_that_does_not_take_the_setting_is_reported():
    class Deaf(FakeMill):
        def _write(self, reg, value):
            self._saving = 1

    with pytest.raises(SetupError, match="still reads NC Code"):
        millsetup.set_command_set(Deaf(), nc=False, **FAST)


def test_a_mill_that_stays_busy_gets_nothing_more():
    class Stuck(FakeMill):
        def ctrl_transfer(self, rtype, request, value, index, payload):
            out = super().ctrl_transfer(rtype, request, value, index, payload)
            if rtype == 0xC1 and value == 0x0001 and self.writes():
                return out[:4] + b"\x20" + out[5:]
            return out

    mill = Stuck()
    ticks = iter(range(100))
    with pytest.raises(SetupError, match="stayed busy"):
        millsetup.set_command_set(mill, nc=False, sleep=lambda _s: None,
                                  clock=lambda: next(ticks) * 0.5)
    assert mill.writes() == [(0x3101, H("00"))]


def test_g54_is_read_in_millimetres():
    """machine to g54 to machine.pcapng: 0, 0, -55.64."""
    assert millsetup.g54_origin(FakeMill()) == (0.0, 0.0, -55.64)


def test_travel_and_spindle_range_from_the_start_up_capture():
    mill = FakeMill()
    assert millsetup.travel(mill) == ((0.0, 0.0, -60.5), (203.2, 152.4, 0.0))
    assert millsetup.spindle_range(mill) == (2000, 7000)


@pytest.mark.parametrize("percent", [95, 83, 60, 16])
def test_the_spindle_slider_sends_one_byte_of_percent(percent):
    """speed1.pcapng: ``41 01 06 30 00 00 05 00`` data ``01 30 06 00 5f``."""
    mill = FakeMill()
    assert millsetup.set_spindle_percent(mill, percent, **FAST) == percent
    assert mill.writes() == [(0x3006, bytes([percent]))]


def test_the_spindle_percent_is_believed_only_once_the_mill_echoes_it():
    """The first poll after the write still showed the old value."""
    mill = FakeMill(lag=2)
    assert millsetup.set_spindle_percent(mill, 60, **FAST) == 60


@pytest.mark.parametrize("percent", [0, 15, 101, 7000])
def test_a_percent_vpanel_never_sent_is_not_sent(percent):
    mill = FakeMill()
    with pytest.raises(SetupError, match="16 to 100"):
        millsetup.set_spindle_percent(mill, percent, **FAST)
    assert mill.sent == []


def test_something_that_is_not_an_srm20_is_refused():
    class Other:
        def ctrl_transfer(self, *a):
            return b"\x00" * 8

    assert not millsetup.is_srm20(Other())
    with pytest.raises(SetupError, match="not an"):
        millsetup.read_register(Other(), 0x3100)


def test_a_usb_error_becomes_a_setup_error():
    class Gone:
        def ctrl_transfer(self, *a):
            raise OSError("No such device")

    with pytest.raises(SetupError, match="did not answer"):
        millsetup.status(Gone())
    assert not millsetup.is_srm20(Gone())


def test_the_module_loads_without_pyusb(monkeypatch):
    """pyusb is only for the real device: a machine without it still imports
    this, and is told what to install when it asks for the mill."""
    import builtins
    real = builtins.__import__

    def no_usb(name, *a, **k):
        if name == "usb" or name.startswith("usb."):
            raise ImportError("No module named 'usb'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_usb)
    with pytest.raises(SetupError, match="pyusb is not installed"):
        millsetup.open_mill()
