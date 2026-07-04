# Hardware — SRM-20 SPI prober (Arduino)

Everything needed to drive the SRM-20 over its SPI remote header from an Arduino
Uno lives here and ships with the repo:

| Path | What it is |
|------|------------|
| [`SRM20SPIRemote/`](SRM20SPIRemote/) | The **vendored Roland `SRM20SPIRemote` library** (`.h` + `.cpp` + `keywords.txt` + examples). Official Roland DG ©2014, mirrored from `github.com/shohei/srm20-arduino`. |
| [`srm20_spi_probe/`](srm20_spi_probe/) | **The production sketch** the GUI talks to: bed probing, live position (DRO), jog, touch-off, emergency STOP / abort, and the runaway guard. Flash this. |
| [`srm20_spi_validate/`](srm20_spi_validate/) | Bench sketch used to discover the SPI behaviour (manual position/jog/sensor pokes). |
| [`SRMTest/`](SRMTest/) | Minimal smoke test of the library. |

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
