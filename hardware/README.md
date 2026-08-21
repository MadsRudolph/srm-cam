# Hardware — SRM-20 SPI prober (Arduino)

Everything needed to drive the SRM-20 over its SPI remote header from an Arduino
Uno lives here and ships with the repo:

| Path | What it is |
|------|------------|
| [`SRM20SPIRemote/`](SRM20SPIRemote/) | The **vendored Roland `SRM20SPIRemote` library** (`.h` + `.cpp` + `keywords.txt` + examples). Official Roland DG ©2014, mirrored from `github.com/shohei/srm20-arduino`. |
| [`srm20_spi_probe/`](srm20_spi_probe/) | **The production sketch** the GUI talks to: bed probing, live position (DRO), jog, touch-off, emergency STOP / abort, and the runaway guard. Flash this. |
| [`srm20_spi_validate/`](srm20_spi_validate/) | Bench sketch used to discover the SPI behaviour (manual position/jog/sensor pokes). |
| [`SRMTest/`](SRMTest/) | Minimal smoke test of the library. |

## Flashing (one command, no IDE)

```bash
python scripts/flash_firmware.py
```

Syncs the patched library into your Arduino libraries folder, compiles, uploads
to the auto-detected port, then reads the version back to prove it took. Uses
the `arduino-cli` bundled inside the Arduino IDE — nothing extra to install.
`--compile-only` to just check it builds; `--port COM4` to pin the port.

**Why not just use the IDE:** the sketch includes `<SRM20SPIRemote.h>` with
angle brackets, so the IDE resolves it from `Documents\Arduino\libraries` — not
from this repo. If that copy is stale you get a firmware that builds cleanly and
is quietly missing the `I` and `F` commands (they compile to `NOPATCH` stubs).
The script syncs first, every time, so the two cannot drift.

## Install the library (required — sketches won't compile without it)

The sketches include the library with angle brackets (`#include <SRM20SPIRemote.h>`),
so the Arduino IDE looks in your **libraries folder**, not next to the `.ino`. Copy
(or symlink) the vendored folder there once:

- **Windows:** `Documents\Arduino\libraries\SRM20SPIRemote\`
- **macOS:** `~/Documents/Arduino/libraries/SRM20SPIRemote/`
- **Linux:** `~/Arduino/libraries/SRM20SPIRemote/`

i.e. copy `hardware/SRM20SPIRemote/` into that `libraries/` directory (keep the
folder name `SRM20SPIRemote`), then restart the Arduino IDE. Alternatively use
**Sketch → Include Library → Add .ZIP Library…** on a zip of that folder.

## Flash + wire

1. Open [`srm20_spi_probe/srm20_spi_probe.ino`](srm20_spi_probe/srm20_spi_probe.ino),
   select **Arduino Uno**, and upload. The Uno plugs into the SPI shield on the
   SRM-20's back header; VPanel can stay connected (they coexist).
2. **External touch probe:** copper board **isolated from the bed** (paper/tape
   under it) → **D7** (floats HIGH via the internal pull-up); tool/collet → **GND**.
   Tool touches copper → D7 LOW. Spindle stays **OFF** while probing.
3. Close the Arduino **Serial Monitor** before the GUI opens the port — only one
   program can hold the COM port.

The serial protocol (115200 baud, microns) is documented at the top of
`srm20_spi_probe.ino`; the host side is `gerber2rml/engine/spi_probe.py`. Pins are
`begin(9, 6)` (slave-select D9, ready D6); units are **microns**. See
`docs/2026-06-25-srm20-spi-and-bed-leveling.md` for the full story, including the
STOP / runaway-guard behaviour — **reflash after pulling** to get those safety
fixes.

## Local patch to the Roland library (re-apply if you re-vendor)

`SRM20SPIRemote/` is Roland's code plus three additions, each marked `PATCH:`:

| Addition | Why |
|---|---|
| `getCommandVersion()` made public | It was private, so the machine's own remote-protocol version could never be read. |
| `rawTxRx(byte)` | Escape hatch for opcodes the library doesn't wrap (gaps at 0x14+, 0x45+, 0xa5+). Bench use only — an unknown opcode can move the machine. |
| `setFrameDelayUs()` | The per-byte SS delay was a hard-coded `delay(5)`. That is ~90 ms of pure sleep per `jumpTo`, and the real ceiling on move streaming. |

`SRM20SPIREMOTE_LOCAL_PATCH` is defined in the header; the sketch `#ifdef`s on
it, so it still compiles against a pristine upstream copy — the `I` and `F`
commands just answer `E ... NOPATCH`.

## Firmware v3 (2026-08) — the "retire VPanel" command set

An audit found the project was calling 5 of the library's 17 SPI commands. v3
adds the rest, so they can be **tested** on the machine (nothing depends on them
yet — several are known-dead here, e.g. `scanTo`/`readSensor`).

| Cmd | Drives | Replaces in VPanel |
|---|---|---|
| `S <rpm>` | `turnSpindle` | The Spindle Speed slider — RPM has been a VPanel-only setting |
| `X` | `getStatus` + `getActualSpindleSpeed` | The whole status display. v2 read 1 of 64 bits |
| `~` `^` `%` `K` | `suspendJob` / `resumeJob` / `stopMoving` / `cancelJob` | Pause, Resume, Stop |
| `Y` | `jumpToView` | The View button |
| `I` | `getCommandVersion` | — (a real "is an SRM-20 there?" handshake) |
| `F <us>` | SPI framing delay | — (throughput experiment) |
| `N <dx> <dy> <dz> <s>` | timed relative move | — (calibrates `jumpTo`'s speed units) |
| `A <0|1>` | arms the status guard | — |

**Safety changes that come with it:**

- **The status guard.** v2's `waitForMotorStop` could not tell "finished" from
  "paused" and inferred a pause from an **8-second timeout** — the ambiguity
  behind the near-miss in `docs/2026-06-25-srm20-spi-and-bed-leveling.md`. v3
  reads the machine's own PAUSE / COVER-OPEN / FATAL bits and stops at once,
  debounced over 2 reads. `A 0` disarms it if those bits prove unreliable here.
- **Transport commands work mid-move.** v2's abort scan ate every byte that
  arrived during a move, so a pause or stop sent while moving did nothing.
- **Spindle deadman.** A spindle started over SPI stops by itself if the host
  goes quiet for 10 s. Any caller that starts it must keep talking.
- **`!` now also stops the spindle**, drops the move in flight, and releases a
  pause hold before lifting.

**Testing it:** the GUI's **Machine test…** button (machine dock, Professional
mode) runs each command and reports PASS / FAIL / UNKNOWN with a pasteable
report. `scripts/srm20_bench.py` does the same from the command line and adds
the framing-delay and speed-unit sweeps. Read-only by default; motion and
spindle tests are separately armed.

## Firmware v2 (2026-07)

Reflash to get:

- **Debounced contact** — 3 consecutive LOW reads, so stepper EMI can't fake a touch.
- **Two-stage verified touch** — coarse 25 um contact, lift 150 um, re-descend at
  10 um (machine native step); the touches must agree within 60 um or the point
  reports `E ... UNSTABLE` instead of poisoning the height map.
- **`B`** — re-touch the datum reference mid-grid; the host uses it to measure and
  correct Z drift (spindle warm-up, board settling) across a long run.
- **`W`** — zero the work-origin Z on the copper: verified touch-off, then
  `setOrigin(x, y, touchZ)`, lift 2 mm. NOTE: this writes the origin VPanel
  displays (User CS). Verify VPanel's **G54** Z once before trusting it for NC
  jobs — on our machine G54 has not been observed to follow it.
- **`V`** — `V 2 <features>` so the host can detect firmware capabilities.
