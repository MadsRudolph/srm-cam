"""Drive the SRM-20 grid prober (hardware/srm20_spi_probe.ino) over serial.

Protocol (see the .ino): send ``D`` to latch the datum at the current position,
then ``P <id> <x> <y>`` per point where x/y are datum-LOCAL offsets in microns.
The board replies ``R <id> <x> <y> <touchZ>`` (microns) on contact, or
``E <id> <reason>`` on failure. ``#``-prefixed lines are human logs (ignored).

The probe touchZ is an absolute machine Z (microns); the surface *deviation* used
by :class:`gerber2rml.engine.leveling.HeightMap` is ``touchZ - touchZ(reference)``
(see :func:`deviations_mm`), so the cut must zero Z on the surface at that same
reference point.
"""
import time


class ProbeError(RuntimeError):
    pass


def _open_serial(port, baud, timeout):
    import serial  # lazy: pyserial only needed when actually probing
    return serial.Serial(port, baud, timeout=timeout)


def _read_line(ser, deadline, should_abort=None):
    """Next non-comment line (stripped str), skipping ``#`` logs. None on timeout
    or when ``should_abort()`` turns true (so a STOP is responsive even mid-read;
    the serial port must be opened with a short read timeout for this to poll)."""
    while time.monotonic() < deadline:
        if should_abort is not None and should_abort():
            return None
        raw = ser.readline()
        if not raw:
            continue
        s = raw.decode("ascii", "replace").strip()
        if s and not s.startswith("#"):
            return s
    return None


def send_abort(ser):
    """Tell the prober to STOP descending and lift to safe Z (the firmware ``!``).
    Safe to call any time; failures are swallowed (the caller is already aborting)."""
    try:
        ser.write(b"!\n")
        ser.flush()
    except Exception:
        pass


def _interp_drift(retouches, s):
    """Piecewise-linear reference Z (um) at sequence position ``s`` from
    ``retouches`` = [(after_n_points, z_um), ...] (in order). Clamped ends."""
    if s <= retouches[0][0]:
        return retouches[0][1]
    for (a0, z0), (a1, z1) in zip(retouches, retouches[1:]):
        if s <= a1:
            t = (s - a0) / max(a1 - a0, 1e-9)
            return z0 + t * (z1 - z0)
    return retouches[-1][1]


def probe_grid(port, points, baud=115200, point_timeout=90.0,
               startup_wait=2.0, ack_timeout=3.0, ack_tries=3,
               serial_factory=None, on_result=None, should_abort=None,
               outlier_mm=1.5, retouch_every=0, drift_log=None):
    """Probe a grid and return per-point results.

    ``points``: list of ``(id, x_um, y_um)`` datum-local offsets (ints).
    Returns a list of dicts ``{"id", "x", "y", "z"}`` with ``z`` the touch height
    in microns (or ``None`` + ``"error"`` on failure). ``on_result(d)`` is called
    as each point completes, for live UI updates.

    ``startup_wait`` covers the Uno's auto-reset when the port opens; the datum
    (``D``) handshake is retried ``ack_tries`` times in case the first lands
    during the reboot.

    Runaway guard: if a touch comes back more than ``outlier_mm`` deeper than the
    first measured point (no real board surface varies that much — it means the
    probe missed copper and the bit is heading into the board/bed), the grid is
    aborted: the tool is lifted (``!``) and probing stops. The firmware enforces
    the same limit in real time; this is the host-side backstop. Set
    ``outlier_mm=None`` to disable.

    Drift compensation (``retouch_every=N``, firmware v2): the datum reference is
    re-touched (``B``) before the first point and after every N points. If the
    reference Z drifts over the run (spindle warm-up, board settling — exactly
    what poisons a mesh row probed minutes after another), each point's z is
    corrected by the drift interpolated at the moment it was probed. Raw values
    are kept in ``z_raw``; ``drift_log`` (a list, if given) receives
    ``{"after": n, "z": z_um}`` per re-touch. Correction is applied to the
    RETURNED results — ``on_result`` still sees raw values live.
    """
    factory = serial_factory or _open_serial
    # Short read timeout so reads return often and a STOP stays responsive; the
    # real per-point limit is enforced by point_timeout deadlines below.
    ser = factory(port, baud, 0.5)
    try:
        if startup_wait:
            time.sleep(startup_wait)         # Uno reboots on port open — let it boot
        try:
            ser.reset_input_buffer()         # drop the boot banner
        except Exception:
            pass
        ack = None
        for _ in range(max(1, ack_tries)):
            ser.write(b"D\n")
            ack = _read_line(ser, time.monotonic() + ack_timeout)
            if ack and ack.startswith("D"):
                break
        if ack is None or not ack.startswith("D"):
            raise ProbeError(
                f"no datum ack from {port} (got {ack!r}). Is the prober sketch "
                f"running and the Serial Monitor closed?")
        results = []
        ref_z = None                          # first measured Z (runaway reference)
        retouches = []                        # [(after_n_points, ref_z_um)]

        def do_retouch():
            ser.write(b"B\n")
            line = _read_line(ser, time.monotonic() + point_timeout, should_abort)
            if line and line.startswith("B "):
                try:
                    z = int(line.split()[1])
                except (ValueError, IndexError):
                    return
                retouches.append((len(results), z))
                if drift_log is not None:
                    drift_log.append({"after": len(results), "z": z})
            # a failed re-touch (E/timeout) just skips this checkpoint

        if retouch_every:
            do_retouch()                     # baseline before the first point
        for (pid, x, y) in points:
            if should_abort is not None and should_abort():
                send_abort(ser)              # lift the tool, then stop the grid
                break
            ser.write(f"P {int(pid)} {int(x)} {int(y)}\n".encode())
            line = _read_line(ser, time.monotonic() + point_timeout, should_abort)
            if should_abort is not None and should_abort():
                send_abort(ser)
                break
            d = {"id": int(pid), "x": int(x), "y": int(y), "z": None}
            if line and line.startswith("R"):
                parts = line.split()
                if len(parts) >= 5 and int(parts[1]) == int(pid):
                    d["z"] = int(parts[4])
                else:
                    d["error"] = f"bad reply {line!r}"
            elif line and line.startswith("E"):
                d["error"] = line
            else:
                d["error"] = f"timeout (got {line!r})"

            # A contact FAR DEEPER than the surface is the genuinely suspicious case
            # (the bit punched into the board) -> stop the whole grid.
            deep_outlier = False
            if d["z"] is not None and outlier_mm is not None:
                if ref_z is None:
                    ref_z = d["z"]
                elif (ref_z - d["z"]) > outlier_mm * 1000.0:     # microns; deeper = lower Z
                    d["error"] = (f"outlier: {(ref_z - d['z']) / 1000.0:.2f} mm deeper "
                                  f"than the surface")
                    d["z"] = None
                    deep_outlier = True

            results.append(d)
            if on_result:
                on_result(d)

            if deep_outlier:
                send_abort(ser)              # suspicious deep touch -> lift + stop
                break
            if d["z"] is None and ref_z is None:
                # missed before any surface was found -> can't level; stop so the
                # operator can fix the datum/probe rather than plunge blindly.
                send_abort(ser)
                break
            # else a miss WITH a known surface: the firmware safely capped that
            # point (no copper there) -> record it as missing and keep probing.
            if (retouch_every and len(results) % retouch_every == 0
                    and len(results) < len(points)
                    and not (should_abort is not None and should_abort())):
                do_retouch()
        else:
            # Grid ran to completion: close the drift record with a final
            # re-touch, so the last points aren't extrapolated from a stale
            # checkpoint (they're the ones probed FURTHEST from the baseline).
            if (retouch_every and results
                    and (not retouches or retouches[-1][0] != len(results))
                    and not (should_abort is not None and should_abort())):
                do_retouch()

        # Apply the drift correction: the reference surface measured at (at
        # least) two moments defines drift as a function of grid progress; each
        # point is corrected by the drift at the moment it completed.
        if len(retouches) >= 2:
            base = retouches[0][1]
            for i, d in enumerate(results):
                if d.get("z") is None:
                    continue
                drift = _interp_drift(retouches, i + 0.5) - base
                d["z_raw"] = d["z"]
                d["z"] = int(round(d["z"] - drift))
        return results
    finally:
        ser.close()


# SPI per-byte framing delay used for normal work, in microseconds.
#
# Roland hard-coded 5000. Measured on the machine 2026-08-21, transfers stay
# clean all the way down to 50 us — but corruption there is intermittent and
# this link drives a bit toward a board, so the default keeps a 10x margin over
# the lowest clean value rather than chasing the floor. At 500 us a position
# read costs ~13 ms instead of ~89 ms, which is most of the available win:
# probing and streaming are dominated by these transfers.
#
# Raise it back to 5000 if reads ever look unstable; scripts/srm20_bench.py
# --frame-soak is how to justify moving it.
DEFAULT_FRAME_US = 500


def open_link(port, baud=115200, startup_wait=2.0, serial_factory=None,
              prime=True, frame_us=None):
    """Open the prober serial port and wait out the Uno's reset-on-open.

    ``prime`` sends one throwaway position query. Measured on the machine: the
    FIRST SPI transaction after the Uno resets comes back all zeros, so whatever
    command a caller happens to run first would read as garbage — a status word
    of 0x00000000, a position of 0,0,0. Burning one read here means every
    caller's first real command is clean.

    ``frame_us`` sets the SPI framing delay for this session (None leaves the
    firmware's own default alone). Needs the patched library; silently does
    nothing without it, which is the right failure — slow but correct.
    """
    ser = (serial_factory or _open_serial)(port, baud, 1.0)
    if startup_wait:
        time.sleep(startup_wait)
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    if prime:
        try:
            query_position(ser)
        except Exception:
            pass
    if frame_us is not None:
        try:
            frame_delay(ser, frame_us)
        except Exception:
            pass
    return ser


def query_position(ser, timeout=1.0):
    """Send ``Q`` and parse ``Q x y z [touch]`` (microns) ->
    ``(x_mm, y_mm, z_mm, touch_bool)`` or None. A single fast read (no stable
    filtering) so jogging shows live; the caller rejects implausible jumps
    (garbage SPI reads). ``touch`` is the external probe contact state (the 5th
    field; defaults False for an older sketch without it).

    Resyncs first (see :func:`_flush_stale`): a stale line left by an
    interrupted move would otherwise be mistaken for this query's answer and
    report the position as unreadable."""
    _flush_stale(ser)
    ser.write(b"Q\n")
    deadline = time.monotonic() + timeout
    while True:
        line = _read_line(ser, deadline)
        if line is None:
            return None
        if not line.startswith("Q"):
            continue                      # someone else's reply — keep looking
        parts = line.split()
        if len(parts) < 4:
            return None
        try:
            touch = len(parts) >= 5 and int(parts[4]) != 0
            return (int(parts[1]) / 1000.0, int(parts[2]) / 1000.0,
                    int(parts[3]) / 1000.0, touch)
        except ValueError:
            return None


def touch_off(ser, timeout=40.0, should_abort=None):
    """Send ``T`` (descend from the current XY until the probe contacts, then
    stop). Returns ``(x_mm, y_mm, z_mm)`` of the contact, or None on no-contact
    /error/abort. If ``should_abort()`` turns true mid-descent, sends ``!`` so the
    tool lifts and stops."""
    ser.write(b"T\n")
    line = _read_line(ser, time.monotonic() + timeout, should_abort)
    if should_abort is not None and should_abort():
        send_abort(ser)
        return None
    if line and line.startswith("T"):
        parts = line.split()
        if len(parts) >= 4:
            try:
                return (int(parts[1]) / 1000.0, int(parts[2]) / 1000.0,
                        int(parts[3]) / 1000.0)
            except ValueError:
                return None
    return None


def jog_to(ser, x_um, y_um, timeout=20.0):
    """Send ``J x y`` (jog to absolute machine XY, microns) and wait for the
    ``J x y`` ack. Returns True on success."""
    ser.write(f"J {int(x_um)} {int(y_um)}\n".encode())
    line = _read_line(ser, time.monotonic() + timeout)
    return bool(line and line.startswith("J"))


def firmware_version(ser, timeout=1.5):
    """Send ``V`` -> ``(version:int, features:set[str])``. Older sketches don't
    answer ``V`` at all -> ``(1, set())`` after the timeout, so callers can gate
    v2-only features (``"retouch"``, ``"zeroz"``, ...) cleanly."""
    ser.write(b"V\n")
    line = _read_line(ser, time.monotonic() + timeout)
    if line and line.startswith("V "):
        parts = line.split()
        try:
            ver = int(parts[1])
        except (ValueError, IndexError):
            return (1, set())
        feats = set(parts[2].split(",")) if len(parts) >= 3 else set()
        return (ver, feats)
    return (1, set())


def zero_z(ser, timeout=60.0, should_abort=None):
    """Send ``W`` (verified touch-off, then set the work-origin Z to the copper
    surface). Returns the new origin ``(ox_mm, oy_mm, oz_mm)`` or None on
    error/abort. NOTE: writes the origin VPanel displays (User CS); verify
    VPanel's G54 Z once before trusting it for NC jobs."""
    ser.write(b"W\n")
    line = _read_line(ser, time.monotonic() + timeout, should_abort)
    if should_abort is not None and should_abort():
        send_abort(ser)
        return None
    if line and line.startswith("W "):
        parts = line.split()
        if len(parts) >= 4:
            try:
                return (int(parts[1]) / 1000.0, int(parts[2]) / 1000.0,
                        int(parts[3]) / 1000.0)
            except ValueError:
                return None
    return None


# --- v3: the machine remote (status, spindle, job control, calibration) -----
# Everything below drives an SPI command the project shipped without ever
# calling — see docs/2026-08-21-spi-command-audit.md. None of it is proven on
# the machine yet, so every function FAILS SOFT (None / False, never an
# exception) and the caller decides whether the feature exists. The GUI's
# Machine test panel is what turns "unproven" into "proven".

# The system status word, decoded from Roland's own getStatus example
# (hardware/SRM20SPIRemote/examples/getStatus/getStatus.ino). v2 firmware read
# only ``moving`` and left the rest of the word unexamined.
SYSTEM_BITS = (
    (0x00000020, "paused",  "paused"),
    (0x00000040, "error",   "error"),
    (0x00000800, "moving",  "motors running"),
    (0x00001000, "fatal",   "fatal error"),
    (0x00010000, "spindle", "spindle running"),
    (0x00020000, "cover",   "cover open"),
)
STATE_MASK = 0x00000007          # machine state code; the values are unmapped
# The remote word carries one bit we care about: the machine telling us it
# refused the last command. Nothing in the project has ever looked at it, so a
# rejected move has always been indistinguishable from a completed one.
REMOTE_BITS = (
    (0x00000010, "cmderr", "last remote command rejected"),
)


def decode_status(system, remote):
    """Decode the raw ``X`` words into ``{name: bool}`` plus ``state``/raw.

    Pure and hardware-free so the bit table has one home and can be unit
    tested; the firmware deliberately forwards the raw words rather than
    decoding them on the Arduino.
    """
    out = {"state": system & STATE_MASK, "system": system, "remote": remote}
    for mask, key, _desc in SYSTEM_BITS:
        out[key] = bool(system & mask)
    for mask, key, _desc in REMOTE_BITS:
        out[key] = bool(remote & mask)
    return out


def _flush_stale(ser):
    """Drop anything sitting in the input buffer.

    This protocol is strict request/response, so bytes waiting *before* we send
    a command are by definition left over from something else — an interrupted
    move's late ``E N ABORT``, a ``% ok`` that arrived after its move finished.
    Without this, one stray line desyncs the stream permanently: every command
    reads the PREVIOUS command's reply and the failures march forward one step
    at a time, which is exactly what the first machine test run showed.
    """
    try:
        ser.reset_input_buffer()
    except Exception:
        pass


def _ack(ser, cmd, prefix, timeout=3.0, should_abort=None, return_error=False):
    """Send ``cmd``, resync, and return the reply's fields (prefix included).

    Returns None when the board reports an error or says nothing — firmware
    older than v3 simply does not answer these. With ``return_error`` the
    result is ``(parts_or_None, error_line_or_None)`` so a caller can say *why*
    rather than just "no answer".
    """
    _flush_stale(ser)
    try:
        ser.write((cmd + "\n").encode())
    except Exception:
        return (None, "write failed") if return_error else None
    deadline = time.monotonic() + timeout
    err = None
    while True:
        line = _read_line(ser, deadline, should_abort)
        if line is None:
            break
        if line.split()[:1] == [prefix]:
            parts = line.split()
            return (parts, None) if return_error else parts
        if line.startswith("E "):
            # The board's own error for this command — terminal, and far more
            # useful to report than a bare timeout.
            err = line
            break
        # Anything else is an unrelated ack that overtook us (e.g. '~ ok'
        # emitted mid-move); skip it rather than mistaking it for the reply.
    return (None, err) if return_error else None


def machine_status(ser, timeout=2.0, retries=2):
    """Send ``X`` -> decoded status dict (plus ``rpm``), or None.

    This is the whole VPanel status display: paused, cover open, error, fatal,
    spindle state and the actual spindle RPM.

    An all-zero or all-ones system word is what a FAILED SPI transfer looks
    like, not an idle machine, so those are retried — the project's standing
    rule is never to trust a single SPI read. If every attempt comes back that
    way the value is returned anyway, so a genuinely dead link still reports as
    dead rather than as None.
    """
    last = None
    for _ in range(max(1, retries + 1)):
        parts = _ack(ser, "X", "X", timeout)
        if not parts or len(parts) < 4:
            continue
        try:
            st = decode_status(int(parts[1]), int(parts[2]))
            st["rpm"] = int(parts[3])
        except ValueError:
            continue
        last = st
        if st["system"] not in (0, 0xFFFFFFFF):
            return st
    return last


def set_spindle(ser, rpm, timeout=3.0):
    """Send ``S <rpm>`` (0 = off) -> the RPM the firmware accepted, or None.

    The firmware clamps to the SRM-20's rated 7000 RPM, refuses to start with
    the lid open (``E S COVER``), and stops the spindle by itself if the host
    goes quiet for 10 s — so a caller that starts the spindle MUST keep talking
    to the board (polling :func:`machine_status` is enough).
    """
    parts = _ack(ser, f"S {int(rpm)}", "S", timeout)
    if not parts or len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def spindle_off(ser):
    """Stop the spindle, swallowing every failure (used on abort paths, where
    the caller is already in trouble and must not be derailed)."""
    try:
        ser.write(b"S 0\n")
        ser.flush()
    except Exception:
        pass


def suspend_job(ser, timeout=3.0):
    """VPanel's Pause (``suspendJob``). True if the board acked."""
    return _ack(ser, "~", "~", timeout) is not None


def resume_job(ser, timeout=3.0):
    """VPanel's Resume (``resumeJob``). True if the board acked."""
    return _ack(ser, "^", "^", timeout) is not None


def stop_moving(ser, timeout=3.0):
    """``stopMoving`` — drop the move in flight. This is what lets an abort
    interrupt a LONG move instead of waiting for it to finish."""
    return _ack(ser, "%", "%", timeout) is not None


def stop_moving_now(ser):
    """Halt motion, fire-and-forget — no ack wait, every failure swallowed.

    The version to call when something has already gone wrong. Waiting for an
    ack while the machine is still travelling is the wrong trade: the byte is
    picked up by the firmware's mid-move abort scan either way.
    """
    try:
        ser.write(b"%\n")
        ser.flush()
    except Exception:
        pass


def cancel_job(ser, timeout=3.0):
    """VPanel's Stop (``cancelJob``); the firmware also stops the spindle."""
    return _ack(ser, "K", "K", timeout) is not None


def jump_to_view(ser, speed=None, timeout=30.0):
    """VPanel's View button (``jumpToView``) — MOVES the head forward for a bit
    change or board swap. True if the board acked the completed move."""
    cmd = "Y" if speed is None else f"Y {int(speed)}"
    return _ack(ser, cmd, "Y", timeout) is not None


def command_version(ser, timeout=3.0):
    """The MACHINE's remote-command version (``getCommandVersion``), or None.

    Distinct from :func:`firmware_version`, which is our own sketch's. Needs
    the patched library (the call is private upstream) — an unpatched build
    answers ``E I NOPATCH``, which reads as None here.
    """
    parts = _ack(ser, "I", "I", timeout)
    if not parts or len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def frame_delay(ser, us=None, timeout=3.0):
    """Get (``us=None``) or set the SPI per-byte framing delay, in microseconds.

    Roland hard-coded 5000 us. At that rate a single ``jumpTo`` spends ~90 ms
    asleep and a status poll ~55 ms, which is the real ceiling on how fast
    moves can be streamed. Returns the delay now in effect, or None (unpatched
    library / older firmware).
    """
    cmd = "F" if us is None else f"F {int(us)}"
    parts = _ack(ser, cmd, "F", timeout)
    if not parts or len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def status_guard(ser, on=None, timeout=3.0):
    """Get/set the firmware's v3 status guard (stop on PAUSE / COVER / FATAL).

    Armed by default because it is strictly safer than v2's 8-second stall
    heuristic — but if the status bits turn out to be unreliable on this
    machine it can be disarmed rather than causing spurious aborts.
    """
    cmd = "A" if on is None else f"A {1 if on else 0}"
    parts = _ack(ser, cmd, "A", timeout)
    if not parts or len(parts) < 2:
        return None
    return parts[1] == "1"


def timed_move(ser, dx_um=0, dy_um=0, dz_um=0, speed=-1, timeout=120.0,
               should_abort=None, last_error=None):
    """Send ``N`` — a relative move timed ON THE BOARD — and return a dict with
    ``ms``, ``dist_um``, ``speed``, the end position in mm, and the derived
    ``mm_per_s``. None on error/abort.

    This is the primitive that calibrates ``jumpTo``'s ``movespeed`` argument
    against real mm/s. The units are Roland-internal and uncalibrated, which is
    the reason move streaming is still marked EXPERIMENTAL. Board-side timing
    keeps the USB round-trip out of the measurement, but the resolution is the
    firmware's status-poll interval (~100 ms at the stock framing delay), so
    measure with moves of several seconds.

    Pass ``last_error`` as a list to receive the board's failure line (e.g.
    ``E N ABORT``) when the move does not complete.
    """
    cmd = f"N {int(dx_um)} {int(dy_um)} {int(dz_um)} {int(speed)}"
    parts, err = _ack(ser, cmd, "N", timeout, should_abort, return_error=True)
    if not parts or len(parts) < 7:
        # Surface the board's reason. 'E N ABORT' means the machine stopped or
        # refused; a bare timeout means it never answered at all. Callers
        # report this, because "the move did not complete" on its own gives
        # nobody anything to act on.
        if last_error is not None:
            last_error.append(err or "no reply")
        # The move lives in the Roland controller, not in the firmware, so
        # giving up on the REPLY does not stop the machine — observed
        # 2026-08-21, a move the host had already declared failed kept driving
        # Y across the table. Halt it explicitly.
        stop_moving_now(ser)
        return None
    try:
        ms, dist, sp = int(parts[1]), int(parts[2]), int(parts[3])
        x, y, z = (int(parts[4]), int(parts[5]), int(parts[6]))
    except ValueError:
        return None
    # mm/s = (dist_um / 1000) / (ms / 1000) = dist_um / ms
    return {"ms": ms, "dist_um": dist, "speed": sp,
            "x_mm": x / 1000.0, "y_mm": y / 1000.0, "z_mm": z / 1000.0,
            "mm_per_s": (dist / ms) if ms > 0 else None}


def deviations_mm(results, ref_id=0):
    """Map probe results (microns) to ``{id: dz_mm}`` deviations relative to the
    reference point's height. Skips points that didn't contact."""
    by_id = {r["id"]: r["z"] for r in results if r.get("z") is not None}
    if ref_id not in by_id:
        if not by_id:
            return {}
        ref_id = next(iter(by_id))           # fall back to first good point
    z0 = by_id[ref_id]
    return {i: (z - z0) / 1000.0 for i, z in by_id.items()}


# --- finding the board ------------------------------------------------------
# USB-serial chips these boards actually ship with. The lab's Uno is a CH340
# clone; genuine Unos use an ATmega16U2 under Arduino's own VID.
BOARD_VIDS = {
    "1A86": "CH340 (Uno clone)",
    "2341": "Arduino",
    "2A03": "Arduino (.org)",
    "0403": "FTDI",
    "10C4": "CP210x",
}


def rank_ports(ports):
    """Order candidate serial ports, most-likely-Arduino first.

    ``ports`` is a sequence of ``(device, hwid)`` pairs — exactly what
    ``serial.tools.list_ports.comports()`` yields the parts of. Returns
    ``[(device, why), ...]``: ports whose hwid carries a known USB-serial VID
    come first, each labelled with the chip; everything else follows in the
    order given, labelled ``"unknown device"``.

    This exists because picking the wrong port is the commonest way probing
    fails for someone doing it for the first time. On the lab PC the other
    port is Intel AMT Serial-over-LAN — a motherboard feature that will never
    be an Arduino, and nothing on screen tells a beginner that.

    Ordering only. The caller still decides, and a human can always override:
    a board behind an unrecognised chip must stay selectable, so nothing is
    filtered out.
    """
    known, unknown = [], []
    for device, hwid in ports:
        text = (hwid or "").upper()
        for vid, chip in BOARD_VIDS.items():
            if f"VID:PID={vid}:" in text or f"VID_{vid}" in text:
                known.append((device, chip))
                break
        else:
            unknown.append((device, "unknown device"))
    return known + unknown


def best_port(ports):
    """The single most likely Arduino port, or None if nothing looks like one.

    None rather than a guess: silently probing on the wrong port produces a
    confusing timeout, and telling someone "no board found, check the cable"
    is far more use than that.
    """
    for device, why in rank_ports(ports):
        if why != "unknown device":
            return device
    return None
