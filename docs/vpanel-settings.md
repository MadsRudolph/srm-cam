# The mill's settings without VPanel

SRM-CAM sends a job to the SRM-20 through its printer interface. Three things
it relies on were set only in Roland's **VPanel**, which is Windows-only:
Setup ▸ Command Set, the G54 origin, and the spindle speed. This is what
VPanel puts on the wire for each, how that was found, and what SRM-CAM does
with it (`gerber2rml/engine/millsetup.py`, `gerber2rml/gui2/millsettings.py`).

Nothing here comes from Roland's code. It is all from watching one mill's USB
traffic while VPanel 1.10 was used in the ordinary way.

## How it was found

USBPcap + Wireshark 4.6.9 on Windows 11, capturing only the mill
(`0B75:039F`), 2026-11-15, the DTU lab SRM-20. One capture per action:

| Capture | What was done in VPanel |
|---|---|
| `opstart.pcapng` | VPanel started with the mill already on |
| `tomgang.pcapng` | 15 s, nothing touched |
| `jog.pcapng` | Jogged X, Y and Z in steps of different sizes |
| `speed1.pcapng` | The **Spindle** slider dragged 100 → 95 → 83 → 60 |
| `speed2.pcapng` | The **Speed** slider dragged 100 → 90 → 80 → 70 → 60 |
| `Spindle on, speed high + 100%.pcapng` | Spindle ON, 4 s, OFF, slider at 100 % |
| `spindel lav.pcapng` | The same with the slider pulled all the way down |
| `machine to g54 to machine.pcapng` | The coordinate display switched Machine → G54 → Machine |
| `command-set-nc-rml-nc.pcapng` | Setup ▸ Command Set: NC Code → RML-1 → NC Code |

The captures are the operator's and are not in the repository.

## The channel

Not the printer interface. The device is a printer-class device with a bulk
OUT (`0x01`) and a bulk IN (`0x82`) endpoint, and **no capture holds a single
bulk packet**: everything VPanel does outside a job is a vendor control
transfer on endpoint 0. That is why a CUPS queue or the Windows spooler
cannot carry it, and why SRM-CAM needs direct USB access (pyusb + libusb).

Four transfers make up the whole protocol. `bRequest` is always `01`,
`wIndex` always `0000`.

| Direction | Setup packet | Data |
|---|---|---|
| Request a register | `41 01 <lo> <hi> 00 00 04 00` | `01 <hi> <lo> 00` |
| Set a register | `41 01 <lo> <hi> 00 00 <4+n> 00` | `01 <hi> <lo> 00` + n value bytes |
| Status header | `c1 01 01 00 00 00 08 00` | ← `82 <busy> <spindle> 01 <working> 00 00 <n>` |
| Fetch the answer | `c1 01 03 00 00 00 <n> 00` | ← the n bytes the header announced |
| Poll | `c1 01 00 01 00 00 38 00` | ← the header + a 48-byte live block |

The register number travels twice, little-endian in `wValue` and big-endian
in the data, and the two always agree. VPanel asks the header before it
fetches anything; the header's last byte is the length waiting. For a
one-byte answer VPanel still asks for three and gets one. Numbers are
little-endian 32-bit, lengths in microns.

The header's fifth byte is `20` or `40`, with a length of zero, while the
mill is still working on the last request, and `00` when the answer is
there. In the captures that shows only after a write (`20` for about
150 ms), because they were taken through VirtualHere, which put 70 ms
between any two transfers. Directly on a Mac's USB port the first header
after a *read* request was not ready in 128 of 160 tries; the answer followed
within 7 ms. `millsetup._ready` asks again until the byte is `00` before
anything is fetched or sent.

VPanel polls about five times a second. The 56 bytes:

| Bytes | Meaning | How it is known |
|---|---|---|
| 0 | `82` | constant |
| 1 | busy: `09` during a jog, `01` while the spindle runs up or down | `jog`, both spindle captures. Bits not mapped |
| 2 | spindle on | `01` from the start command to the stop |
| 4 | `20` or `40` while the mill works on the last request | every write; every fast read |
| 7 | `30`, the length of what follows | constant |
| 8–19 | X, Y, Z, machine coordinates | follows every jog; matched VPanel's display |
| 32–35 | spindle reading | see "Spindle speed" |
| 38 | the Speed slider, percent | `speed2` |
| 39 | `64` in every capture | unknown |
| 40 | the Spindle slider, percent | `speed1`, `spindel lav` |

## Registers

| Register | R/W | Value | Capture | Status |
|---|---|---|---|---|
| `3100` | read | 1 byte: `00` RML-1, `01` NC Code | `command-set` | **proven**, both ways |
| `3101` | write | the same byte | `command-set` | **proven**, both ways |
| `3200` | read | 3 bytes, `00 00 00` | `command-set` | read when Setup opens; meaning unknown |
| `3201` | write | the 3 bytes read from `3200` | `command-set` | sent after every `3101`; meaning unknown |
| `3203` | read | G54 X, Y, Z + 3 zero words | `machine to g54` | read 0, 0, −55640 |
| `3006` | write | 1 byte, Spindle slider percent | `speed1` | **proven**: 95, 83, 60 echoed in the poll |
| `0258` | write | 1 byte, Speed slider percent | `speed2` | proven; not used by SRM-CAM |
| `3004` | write | 4 bytes: `7000` starts the spindle, `0` stops it | both spindle captures | seen; **not used** |
| `0262` | write | `FF FF 00 00` + X, Y, Z + 3 zero words: move to machine XYZ | `jog` | seen; **not used** |
| `0251` | read | X, Y, Z + 3 zero words | `jog` | read before each jog |
| `02C3` | read | 4 zero bytes | `jog` | read before each jog; unknown |
| `025B` | read | travel: (0, 0, −60500) to (203200, 152400, 0) | `opstart` | matches the SRM-20's work area |
| `3003` | read | 2000, 7000 | `opstart` | the spindle range, as the mill reports it |
| `3005` | read | `64` | `opstart` | probably the Spindle slider read back |
| `0FFF` | read | `02` | `opstart` | unknown |
| `346C`–`3473` | read | 4 zero bytes each | `command-set` | read when Setup opens; unknown |
| `027C` | read | 1800 | `command-set` | read when Setup opens; unknown |
| `0280` | read | six words of 100 | `command-set` | read when Setup opens; unknown |

The motion and spindle-start registers are written down and left alone.
Motion belongs to the Arduino link and the runner, which have a STOP.

## The three settings

### Command Set — solved

`3100` reads it, `3101` writes it. Opening Setup read `01` with NC Code
shown; OK with RML-1 selected wrote `3101 ← 00` then `3201 ← 00 00 00`;
reopening Setup read `00`; OK with NC Code wrote `3101 ← 01` and the same
`3201`.

`millsetup.set_command_set` sends exactly that pair, the `3201` bytes being
whatever `3200` holds at the time, and reads `3100` back before it reports
success. It refuses while the mill is busy or the spindle is on.

### Spindle speed — solved as a percentage

The start command does not carry the speed: `3004` was `7000` with the
slider at the top and `7000` with it at the bottom. The speed is the Spindle
slider, register `3006`, in percent. That is the setting upstream's SPI audit
ran into from the other side: over the Arduino link the spindle only turns on
and off, "at whatever VPanel's slider was last set to".

| Slider | Spindle reading once settled |
|---|---|
| 16 % (all the way down) | about 4300 |
| 100 % | 6476 after 4 s and still rising |

The reading is the mill's own and is **not rpm** as written: the SPI audit
read 8600 on a spindle rated 7000. What speed each percent gives has not been
measured. 16 was the lowest value VPanel sent, so `set_spindle_percent`
accepts 16–100 and nothing else.

### G54 — read, not written

`3203` reads the G54 origin. No capture contains a write to it: switching the
display to G54 changes nothing on the mill, VPanel only starts asking for
`3203` three times a second. The register that sets G54 is therefore still
unknown.

SRM-CAM does not need it. The automatic run needs G54 X/Y at machine 0, 0
(`engine/autorun.py`, `_check_frame`), and reading it is enough to say so
before the run has probed anything.

## What SRM-CAM does with it

- **Machine ▸ The mill's settings…** reads the command set, G54 and the
  spindle slider, and has one button for setting NC Code and one for the
  spindle percentage. Opening it changes nothing.
- **Before an automatic run** the same reading is taken. A mill in RML-1 is
  set to NC Code and the run's log says so. A G54 that is not at 0, 0, or a
  mill that cannot be read over USB, asks before the run goes on.
- macOS (and Linux, where there is no machine link yet). **Not Windows**: the
  Roland driver owns the device there and libusb cannot open it; VPanel is at
  hand on that PC anyway.

## Tried at the mill, and not

**Reading works from a Mac** (2026-11-15, the lab mill, macOS on Apple
silicon, the mill on its `SRM-20` CUPS queue at the same time). libusb sends
the vendor control transfers without configuring, claiming or detaching
anything, and the system's printer driver is not disturbed. 250 reads in a
row returned NC Code, G54 0, 0, −55.64, the travel and the spindle range
with no failure, once the not-ready byte was honoured (see "The channel").

One thing got in the way and is worth knowing: **VirtualHere**. While its
server runs on the Mac and a Windows client has the mill "in use", macOS does
not see the device at all. Stop using it on the client, or quit the server.

**The spindle percentage works from a Mac** (the same day, from the packaged
app's Machine ▸ The mill's settings…). With the spindle off, 60 % was set
and read back as 60 after the sheet was closed and reopened. With the
spindle running, 16 % and then 100 % could be heard as the spindle slowing
and speeding up. So register `3006` is the spindle speed, and it takes
effect on a running spindle.

**The command set has not been written from SRM-CAM yet.** It needs a mill
standing in RML-1 to begin with, which is someone else's decision on a
shared machine; until then it is only what VPanel was seen to do. Still
open:

1. Whether the command-set write behaves from a Mac as it did from VPanel.
2. Whether a settings read can run alongside a job, as VPanel's polling does.
   SRM-CAM does not do it: it reads before the run, never during.
3. Whether the command set and the spindle percentage survive a power cycle.

### Checklist

Someone at the mill, lid closed, bit clear of everything, spindle off. Note
what VPanel showed last: Command Set, the Spindle slider.

1. **Read only.** Machine ▸ The mill's settings… . It should show NC Code,
   G54 X 0.00 Y 0.00, and the slider's percentage. (Done 2026-11-15.) If it
   says the mill cannot be reached, nothing has been sent: check that the
   mill is on and that VirtualHere is not holding it.
2. **Spindle percentage, spindle off.** Set 60 %, close, reopen: it reads
   60. Set it back to what it was. (Done 2026-11-15.)
3. **Spindle percentage, spindle on.** From the machine bar start the
   spindle; set 16 %, then 100 %: it audibly slows and speeds up. Stop it.
   (Done 2026-11-15.)
4. **Command set.** Only with the agreement of whoever is responsible for
   the mill - other people's jobs depend on it. There is deliberately no
   button for RML-1, so this needs VPanel once: set RML-1 there, then start
   an automatic **dry run** in SRM-CAM. The log should say the command set
   was RML-1 and is now NC Code, and the run should go on. Check in VPanel
   afterwards that Setup shows NC Code.
5. **Power cycle.** Switch the mill off and on; read the settings again.
