"""Compile and flash the SRM-20 prober firmware — without opening the Arduino IDE.

    python scripts/flash_firmware.py                 # sync lib, compile, upload, verify
    python scripts/flash_firmware.py --compile-only  # just check it builds
    python scripts/flash_firmware.py --port COM4     # pin the port

Why this exists rather than "open the IDE and press upload":

* **The two-library trap.** The sketch includes ``<SRM20SPIRemote.h>`` with angle
  brackets, so the IDE resolves it from ``Documents/Arduino/libraries`` — NOT
  from the repo. The repo's copy carries a local patch (a public
  ``getCommandVersion``, ``rawTxRx``, and a tunable SPI framing delay). If the
  two drift, the IDE silently builds against the stale one and the ``I`` and
  ``F`` commands compile away to ``NOPATCH`` stubs — a firmware that looks fine
  and is quietly missing features. This script syncs the library first, every
  time, so "what is in the repo" and "what is on the board" cannot disagree.
* It is scriptable, so flashing is one command in a session rather than a
  context switch into a GUI.

It uses the ``arduino-cli`` bundled inside the Arduino IDE (no extra install),
falling back to one on PATH.
"""
import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gerber2rml.engine import spi_probe  # noqa: E402
from gerber2rml import platform as plat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "hardware" / "srm20_spi_probe"
LIBRARY = ROOT / "hardware" / "SRM20SPIRemote"
FQBN = "arduino:avr:uno"


def find_cli(explicit=None):
    if explicit:
        return Path(explicit)
    for candidate in plat.arduino_cli_candidates():
        if candidate.is_file():
            return candidate
    found = shutil.which("arduino-cli")
    if found:
        return Path(found)
    raise SystemExit(
        "arduino-cli not found. Install the Arduino IDE (it bundles one) or "
        "pass --cli with a path.")


def user_library_dir():
    """Where the IDE looks for libraries."""
    return plat.arduino_library_dir()


def sync_library(dry_run=False):
    """Mirror the repo's patched library into the IDE's library folder.

    Returns a description of what happened. This is the step that keeps an IDE
    build and a scripted build byte-identical.
    """
    dest = user_library_dir() / LIBRARY.name
    if not dest.exists():
        if dry_run:
            return f"would install {LIBRARY.name} -> {dest}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(LIBRARY, dest)
        return f"installed {LIBRARY.name} -> {dest}"

    diff = filecmp.dircmp(LIBRARY, dest)
    stale = list(diff.diff_files) + list(diff.left_only)
    if not stale:
        return f"already in sync: {dest}"
    if dry_run:
        return f"would update {', '.join(stale)} in {dest}"
    for name in (*diff.diff_files, *diff.left_only):
        src = LIBRARY / name
        if src.is_dir():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest / name)
    return f"updated {', '.join(stale)} in {dest}"


def _run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], text=True, **kw)


def compile_sketch(cli, fqbn=FQBN, warnings="all"):
    # --libraries points at the repo so the patched copy wins even if a stale
    # one is still sitting in the user library folder.
    r = _run([cli, "compile", "--fqbn", fqbn, "--libraries", ROOT / "hardware",
              "--warnings", warnings, SKETCH])
    return r.returncode == 0


def upload(cli, port, fqbn=FQBN):
    r = _run([cli, "upload", "-p", port, "--fqbn", fqbn, SKETCH])
    return r.returncode == 0


def detect_port():
    import serial.tools.list_ports
    ports = [(p.device, p.hwid) for p in serial.tools.list_ports.comports()]
    port = spi_probe.best_port(ports)
    if not port:
        raise SystemExit(
            "No Arduino-like port found. Ports seen: "
            + ", ".join(d for d, _h in ports) + "\nPass --port explicitly.")
    return port


def port_holder_hint():
    """Name the usual suspects that are actually running right now.

    'Port busy' on its own sends people hunting. Only one program can hold the
    port, and it is nearly always one of three: SRM-CAM with the machine
    connected (or the Machine test dialog open, which owns the link for its
    lifetime), the Arduino IDE's Serial Monitor, or a stray terminal.
    """
    suspects = {
        "pythonw": "SRM-CAM (Disconnect, or close the Machine test dialog)",
        "python": "a python script still holding the port",
        "Arduino IDE": "the Arduino IDE (close the Serial Monitor)",
        "putty": "PuTTY",
    }
    found = []
    try:
        import subprocess
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout
        for name, hint in suspects.items():
            if name.lower() in out.lower():
                found.append(hint)
    except Exception:
        pass
    return found


def port_is_free(port):
    """True if we can open the port. Checked BEFORE compiling, so a busy port
    fails in a second instead of after a full build."""
    try:
        import serial
        serial.Serial(port).close()
        return True
    except Exception:
        return False


def verify(port):
    """Talk to the freshly flashed board and report what it says it is."""
    ser = spi_probe.open_link(port)
    try:
        ver, feats = spi_probe.firmware_version(ser)
        print(f"  firmware: v{ver}")
        print(f"  features: {','.join(sorted(feats)) or '(none)'}")
        if ver < 3:
            print("  !! not v3 — the flash did not take")
            return False
        missing = {"info", "frame"} - feats
        if missing:
            print(f"  !! missing {sorted(missing)} — the board was built against "
                  f"an UNPATCHED library, so 'I'/'F' are stubs")
            return False
        st = spi_probe.machine_status(ser)
        if st is None:
            print("  status: no answer to 'X' (is the SRM-20 powered on?)")
        else:
            flags = [k for _m, k, _d in spi_probe.SYSTEM_BITS if st.get(k)]
            print(f"  status: system=0x{st['system']:08x} "
                  f"remote=0x{st['remote']:08x} rpm={st['rpm']} "
                  f"flags={','.join(flags) or 'none'}")
        return True
    finally:
        try:
            ser.close()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="serial port (auto-detected if omitted)")
    ap.add_argument("--fqbn", default=FQBN)
    ap.add_argument("--cli", help="path to arduino-cli")
    ap.add_argument("--compile-only", action="store_true")
    ap.add_argument("--no-sync-library", action="store_true",
                    help="do NOT refresh the IDE's copy of the patched library")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)

    cli = find_cli(args.cli)
    print(f"arduino-cli: {cli}")

    # Check the port before spending time on a build we cannot upload.
    if not args.compile_only:
        port_check = args.port or detect_port()
        if not port_is_free(port_check):
            print(f"\n{port_check} is BUSY — another program is holding it.")
            for hint in port_holder_hint():
                print(f"  - running now: {hint}")
            print("\nFree the port and re-run. Nothing was changed.")
            return 1

    if not args.no_sync_library:
        print("\n[1/4] library sync")
        print("  " + sync_library())
    else:
        print("\n[1/4] library sync SKIPPED")

    print("\n[2/4] compile")
    if not compile_sketch(cli, args.fqbn):
        print("COMPILE FAILED — not uploading.")
        return 1
    if args.compile_only:
        print("\nCompile-only: done.")
        return 0

    port = args.port or detect_port()
    print(f"\n[3/4] upload to {port}")
    print("  (close the Arduino Serial Monitor and disconnect SRM-CAM first —")
    print("   only one program can hold the port)")
    if not upload(cli, port, args.fqbn):
        print("UPLOAD FAILED — is the port busy, or is another program holding it?")
        return 1

    if args.no_verify:
        return 0
    print(f"\n[4/4] verify on {port}")
    return 0 if verify(port) else 1


if __name__ == "__main__":
    sys.exit(main())
