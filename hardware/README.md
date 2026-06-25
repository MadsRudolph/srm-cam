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
