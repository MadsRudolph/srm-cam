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
