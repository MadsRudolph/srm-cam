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


def _read_line(ser, deadline):
    """Next non-comment line (stripped str), skipping ``#`` logs. None on timeout."""
    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        s = raw.decode("ascii", "replace").strip()
        if s and not s.startswith("#"):
            return s
    return None


def probe_grid(port, points, baud=115200, point_timeout=90.0,
               startup_wait=2.0, ack_timeout=3.0, ack_tries=3,
               serial_factory=None, on_result=None):
    """Probe a grid and return per-point results.

    ``points``: list of ``(id, x_um, y_um)`` datum-local offsets (ints).
    Returns a list of dicts ``{"id", "x", "y", "z"}`` with ``z`` the touch height
    in microns (or ``None`` + ``"error"`` on failure). ``on_result(d)`` is called
    as each point completes, for live UI updates.

    ``startup_wait`` covers the Uno's auto-reset when the port opens; the datum
    (``D``) handshake is retried ``ack_tries`` times in case the first lands
    during the reboot.
    """
    factory = serial_factory or _open_serial
    ser = factory(port, baud, point_timeout)
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
        for (pid, x, y) in points:
            ser.write(f"P {int(pid)} {int(x)} {int(y)}\n".encode())
            line = _read_line(ser, time.monotonic() + point_timeout)
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
            results.append(d)
            if on_result:
                on_result(d)
        return results
    finally:
        ser.close()


def open_link(port, baud=115200, startup_wait=2.0, serial_factory=None):
    """Open the prober serial port and wait out the Uno's reset-on-open."""
    ser = (serial_factory or _open_serial)(port, baud, 1.0)
    if startup_wait:
        time.sleep(startup_wait)
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    return ser


def query_position(ser, timeout=1.0):
    """Send ``Q`` and parse ``Q x y z [touch]`` (microns) ->
    ``(x_mm, y_mm, z_mm, touch_bool)`` or None. A single fast read (no stable
    filtering) so jogging shows live; the caller rejects implausible jumps
    (garbage SPI reads). ``touch`` is the external probe contact state (the 5th
    field; defaults False for an older sketch without it)."""
    ser.write(b"Q\n")
    line = _read_line(ser, time.monotonic() + timeout)
    if line and line.startswith("Q"):
        parts = line.split()
        if len(parts) >= 4:
            try:
                touch = len(parts) >= 5 and int(parts[4]) != 0
                return (int(parts[1]) / 1000.0, int(parts[2]) / 1000.0,
                        int(parts[3]) / 1000.0, touch)
            except ValueError:
                return None
    return None


def touch_off(ser, timeout=40.0):
    """Send ``T`` (descend from the current XY until the probe contacts, then
    stop). Returns ``(x_mm, y_mm, z_mm)`` of the contact, or None on no-contact
    /error."""
    ser.write(b"T\n")
    line = _read_line(ser, time.monotonic() + timeout)
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
