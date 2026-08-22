# Dev log — SPI command audit, firmware v3, and the road off VPanel

**Date:** 2026-08-21
**Scope:** audit every command in the vendored Roland SPI library, find what the
project never used, and ship the firmware + tooling to test it on the machine.

**Goal behind it:** retire VPanel. Everything in SRM-CAM, or as much as possible.

---

## 1. The audit

The project drives the machine through Roland's `SRM20SPIRemote` and had been
calling **5 of its 17 commands**.

| Opcode | Call | Was it used? |
|---|---|---|
| `0x01` | `getStatus` | Yes — **1 of 64 bits** (`moving`) |
| `0x02` | `getCommandVersion` | **No** — private in the library, unreachable |
| `0x03` | `requestedData` | Yes (internal read helper) |
| `0x10` | `suspendJob` | **No** |
| `0x11` | `resumeJob` | **No** |
| `0x12` | `cancelJob` | Bench sketch only, for an unrelated purpose |
| `0x13` | `stopMoving` | Bench sketch only, for an unrelated purpose |
| `0x40` | `setOrigin` | Yes |
| `0x41` | `jumpTo` | Yes — carries *all* motion |
| `0x42` | `turnSpindle` | **No** |
| `0x43` | `jumpToView` | **No** |
| `0x44` | `scanTo` | Tested 2026-06, **non-functional here** |
| `0xa0` | `getActualPosition` | Yes |
| `0xa1` | `readSensor` | Tested 2026-06, **garbage here** |
| `0xa2` | `getOrigin` | Yes |
| `0xa3` | `getScanPosition` | Rides `scanTo` — unusable |
| `0xa4` | `getActualSpindleSpeed` | **No** |

Five genuinely unused commands, one massively under-read status word, three
already tried and correctly rejected.

## 2. What each unused command buys

Ranked by how much VPanel it removes.

1. **`turnSpindle` (0x42)** — the big one. The codebase states throughout that
   RPM is a VPanel cut-setting ([backends/gcode.py](../gerber2rml/backends/gcode.py),
   [HANDOFF.md](HANDOFF.md)). That is true of NC/RML — there is no `S` word —
   but not of the SPI link. Roland's own `SRMTest.ino` has
   `turnSpindle(10000)/5000/0` commented out. This is the single hard
   dependency forcing a VPanel round-trip on every wet run.
2. **The 6 unread `getStatus` bits** — highest value, zero risk. See §3.
3. **Job control (0x10–0x13)** — VPanel's Pause / Resume / Stop, in-app.
   `stopMoving` matters most: `!` was only checked *between* moves, so a long
   jog could not be interrupted at all.
4. **`jumpToView` (0x43)** — the View button; fits the flip workflow.
5. **`getActualSpindleSpeed` (0xa4)** — verify spin-up before the plunge instead
   of the blind `G04 X2.` dwell; a real "is it actually turning" interlock.
6. **`getCommandVersion` (0x02)** — a genuine machine handshake at connect.

## 3. The status word was the safety bug

Roland's own example decodes the whole word; the firmware read one bit.

| Bit | Meaning | Before |
|---|---|---|
| `0x0007` | state | unread |
| `0x0020` | **paused** | unread |
| `0x0040` | error | unread |
| `0x0800` | moving | the only bit used |
| `0x1000` | fatal | unread |
| `0x10000` | spindle on | unread |
| `0x20000` | **cover open** | unread |
| `remote & 0x10` | **command rejected** | unread |

`waitForMotorStop` could not distinguish "move finished" from "machine paused",
and inferred a pause from an **8-second timeout**. That ambiguity is exactly the
near-miss recorded in [the 2026-06-25 log](2026-06-25-srm20-spi-and-bed-leveling.md):
a paused machine kept queueing deeper Z moves. Bits `0x20` and `0x20000` answer
it directly and instantly.

`remote & 0x10` matters just as much for streaming: a rejected move was
previously acked as if it had run.

## 4. The blocker nobody had measured

There is **no "run this program" opcode**. Retiring VPanel means streaming every
move (the `M` command). Two things stand in the way:

- **`SPITxRx` sleeps 5 ms per byte** ([SRM20SPIRemote.cpp](../hardware/SRM20SPIRemote/SRM20SPIRemote.cpp)).
  A `jumpTo` is 18 bytes = **~90 ms of pure sleep**; a status poll ~55 ms;
  `readPos` >200 ms. That caps throughput near 5–10 moves/s against jobs of
  thousands of moves. The delay is vendored 2014 code, not a measured
  requirement — it is now tunable (`F`) so the real minimum can be found.
- **Speed units are uncalibrated.** `jumpTo`'s `movespeed` is Roland-internal.
  The new `N` command times a move on the board so mm/s can be derived.

One dependency dissolves for free: `setOrigin ≠ G54` stops mattering under
streaming, because the firmware caches its own origin and sends absolute moves.

## 5. What shipped

- **Library patch** — `getCommandVersion` made public, `rawTxRx` escape hatch,
  tunable framing delay. Guarded by `SRM20SPIREMOTE_LOCAL_PATCH`; see
  [hardware/README.md](../hardware/README.md).
- **Firmware v3** — `S` spindle, `X` status, `~ ^ % K` job control, `Y` view,
  `I` machine version, `F` framing delay, `N` timed move, `A` guard toggle.
  Plus: the status guard replaces the 8 s heuristic, transport commands are
  honoured mid-move, a spindle deadman, and `!` now stops the spindle too.
- **Host driver** — the matching helpers in
  [engine/spi_probe.py](../gerber2rml/engine/spi_probe.py), all failing soft
  (None/False, never an exception) because none of this is proven yet.
- **GUI Machine test panel** — [gui/machinetest.py](../gerber2rml/gui/machinetest.py).
  Every command as a row, PASS / FAIL / UNKNOWN, live status strip, pasteable
  report. Motion and spindle tests separately armed.
- **Bench script** — [scripts/srm20_bench.py](../scripts/srm20_bench.py) for the
  long sweeps (framing delay vs corruption, speed units).

## 6. Results so far (2026-08-21, read-only tests on the machine)

v3 is flashed (`python scripts/flash_firmware.py`). Three previously-unused
commands are now **proven working**:

| Command | Result | Notes |
|---|---|---|
| `getStatus` (0x01) | **WORKS** | `system=0x01000082 remote=0x00000004`, and the remote word varies between reads |
| `getCommandVersion` (0x02) | **WORKS** | Returns `256` = **v1.00**. Previously unreachable — the library kept it private |
| framing delay control | **WORKS** | Reads back 5000 us, settable |

Decoding `0x01000082` against Roland's table: state = 2, and **no** flag bits
set (no error — `0x82` is bits 1 and 7, not the `0x40` error bit). Two bits are
set that Roland's example does not document: **`0x80`** in the system word and
**`0x01000000`**. The remote word's high bits change between reads while
`cmderr` stays clear, so something up there is a counter or timer, not a flag.

Not yet tested: spindle, job control, view, speed units, framing sweep.

**A gotcha found while doing this:** the FIRST SPI transaction after the Uno
resets returns all zeros, so whichever command a tool ran first reported a dead
machine (`system=0x00000000`). `open_link` now burns a priming read, and
`machine_status` retries past an all-0/all-1 word. Anything else talking to this
link should assume the same.

## 6b. First full machine-test run — results and two bugs

| Command | Verdict |
|---|---|
| `getStatus` (0x01) | **WORKS** |
| `getCommandVersion` (0x02) | **WORKS** — 256 = v1.00 |
| **Cover bit** (`0x20000`) | **PROVEN** — follows the lid |
| `jumpToView` (0x43) | **WORKS** — head moved to X 2.1 Y 3.1 |
| Job control (0x10–0x13) | opcodes ack; effect not yet proven |
| Framing delay | **clean down to 50 us** vs Roland's 5000 (89 ms → 4 ms per read) |
| `turnSpindle` (0x42) | **inconclusive** — see below |
| `stopMoving` / pause / speed | **inconclusive** — see below |

**The framing result is the headline.** 5000 → 50 us is ~100×; a `jumpTo` drops
from ~90 ms of framing to ~0.9 ms. That was *the* blocker on move streaming.
Measured over only 12 reads per step, though — soak a candidate
(`--frame-soak`) and leave margin before lowering anything that matters.

Three motion tests and the spindle test failed for **two bugs of ours**, not
machine limitations:

1. **Host serial desync.** `_ack`/`query_position` read exactly one line and
   assumed it was theirs. An interrupted move leaves a late `E N ABORT` in the
   buffer, so every later command read the PREVIOUS command's reply and the
   failures marched forward one step. The giveaway was the speed test: its
   first move "succeeded" and its return "failed". Both now flush stale input
   and drain to the expected prefix.
2. **The guard was keying on an unproven bit.** `GUARD_MASK` included
   `ST_PAUSE` (0x20) on the strength of Roland's label. On this machine that
   bit does **not** behave like "paused": it toggles in response to
   `suspendJob`/`resumeJob`/`stopMoving` in a way that does not match the
   label, and it can sit SET on an idle, healthy machine — whereupon the guard
   aborted **every** move. Guarding on a bit whose meaning is unproven is worse
   than not guarding: it breaks working probe runs. `GUARD_MASK` is now
   `ST_COVER | ST_FATAL` — the bit we proved, plus a genuine fault signal.

**Consequence: the spindle FAIL is probably a false negative.** It ran last,
after the machine was already in the state where everything aborted. Re-test it
alone, and **listen** — `turnSpindle` being ignored and
`getActualSpindleSpeed` being broken (like `readSensor`) look identical from
the host.

### The status bits do not match Roland's labels

Observed on an idle machine: `0x80`, `0x400`, `0x4000` and `0x01000000` all set
at various times, none of them documented in Roland's example, while `0x20`
("pause") moved in the wrong direction. Only `0x20000` (cover) is confirmed.
`scripts/srm20_bench.py --map-bits` watches the word and reports which bit
changes, so the rest can be mapped by doing one known thing at a time. **Do not
add a bit to `GUARD_MASK` until it has been mapped that way.**

## 6c. Second machine-test run — six commands proven

With the desync and guard bugs fixed, everything unblocked:

| Command | Verdict |
|---|---|
| `turnSpindle` (0x42) | **WORKS** — spindle bit set, RPM read climbed, no cmderr. **RPM no longer has to be set in VPanel.** |
| `stopMoving` (0x13) | **WORKS** — 4.84 mm of a 20 mm move before stopping |
| `suspendJob`/`resumeJob` (0x10/0x11) | **WORKS** — 3454 ms vs 1045 ms unpaused; 2.4 s of hold for a 3 s pause |
| `jumpToView` (0x43) | **WORKS** |
| `getStatus`, `getCommandVersion` | **WORK** |
| Default feed rate | **19.1 mm/s** at `movespeed = -1` |

That is the whole VPanel transport panel — Pause, Resume, Stop, View, spindle —
plus live status, driven from SRM-CAM.

**Confirmation that dropping `ST_PAUSE` from the guard was right:** this run had
`flags=paused` set the entire time (`system=0x010040a2`) and every single test
passed. Had that bit still been in `GUARD_MASK`, all of it would have failed
again.

### Two follow-ups this run opened

**1. The spindle numbers are not RPM (or not only RPM).** Commanding `3000` read
back 4476 → 5106 → 5661 → 6325 → 6990 → **8487 and still climbing** after 6 s —
past the commanded value and past the SRM-20's 7000 rating. Either the command
argument, the readback, or both are in some other unit. The reading had not
plateaued, so 8487 is just where the ramp had got to, not a steady state. The
`spindlecal` test now holds each setpoint until the reading settles and walks
LOW → high. **Do not cut using SPI spindle control until the relationship is
known** — the firmware's 7000 clamp is meaningless if the argument is not RPM.

**2. The 8-second move timeout was too short for slow moves.** `speed 2` came
back `E N ABORT`: a 20 mm move at that rate outran the flat 8 s cap that v2 used
for 25 µm probe steps. `waitForMotorStop` now measures time since motion was
last *seen* rather than total move duration, so a legitimately slow move takes
as long as it needs while a machine that stops reporting motion is still caught
(`MOVE_STALL_MS`, with `MOVE_MAX_MS` as a backstop).

## 6d. Third run — the spindle answer, and a runaway

**`turnSpindle` is ON/OFF ONLY. The RPM argument is ignored.**

| commanded | settled reading |
|---|---|
| 500 | 8611 |
| 1000 | 8582 |
| 2000 | 8594 |
| 3000 | 8600 |

Every setpoint lands on the same speed, which is whatever **VPanel's spindle
slider** is set to. So the earlier "RPM no longer has to be set in VPanel" was
**wrong** and is retracted: SPI gives an `M3`/`M5` equivalent — start and stop —
and nothing more. Speed remains a VPanel cut-setting. (`getActualSpindleSpeed`
does read a real, live value: it correctly reported the spindle while it was
being driven from VPanel by hand. The ~8600 figure is above the 7000 rating, so
that number is probably not RPM either.)

The `spindlecal` test now draws this conclusion itself instead of printing
numbers for a human to interpret — all setpoints within 10% → FAIL with
"ON/OFF ONLY".

### The runaway — a move that outlived its own failure

During the speed sweep the Y axis **kept travelling after the test had already
reported failure**. Root cause: the move is queued in the **Roland controller**,
not in the sketch, so giving up on *waiting* for it does nothing to the machine.
Both v2 and v3 had this property; the longer adaptive timeout just made it
visible.

Fixed on both sides:

- **Firmware**: every abnormal exit from `waitForMotorStop` now calls
  `haltMotion()` (`stopMoving`) before returning false. "Stop and lift" is only
  true if the original move is actually dead.
- **Host**: `timed_move` sends `%` when it gives up, and the speed test halts
  and drives the head back to its start position from a `finally`, whatever
  went wrong.

`spindleOff()` is also unconditional now: it used to skip the call when
`spindleRpm == 0`, but the Uno zeroes that on every reset (which happens
whenever a host opens the port), so an abort could silently decline to stop a
spindle that really was turning.

Deliberately NOT done: stopping or adopting a spindle that is already running at
boot. The operator drives the spindle from VPanel by hand, and that would kill
it ten seconds after SRM-CAM connects. The deadman's scope stays narrow — if we
started it and our host goes quiet, we stop it.

## 6e. Shipped into the app

With every command confirmed twice on the machine, they are wired into SRM-CAM
rather than living only in the test panel.

**Machine dock** — `Spindle`, `Pause`, `Resume`, `View`, and a live status strip
(`LID OPEN` / `spindle 8600` / `paused` / `ERROR` / `FAULT`) polled at ~1 Hz off
the machine's own status word. That is VPanel's transport panel, in the app.

**Rules around them**, because a proven command can still do the wrong thing:

- the spindle will not start with the lid open (checked in the app *and* the
  firmware), or with the bit on the probe-wired plate;
- the button follows the MACHINE, so a spindle started from VPanel shows here —
  and disconnecting never stops a spindle SRM-CAM did not start;
- `STOP` now halts the queued move (`stopMoving`) before lifting, instead of
  waiting for a long travel to finish;
- pause/resume routes to whatever owns the serial port — the stream worker
  during a run, the DRO poller otherwise. Sending it to the poller mid-stream
  would have gone nowhere.

**Streaming** — a wet run starts the spindle, waits for it to report running,
stops it however the run ends (including on a crash), holds on Pause, and aborts
if the lid opens mid-job. Two safety paths came out of writing the tests: the
spindle is now stopped when it is commanded on but never *reports* running (it
may well be turning), and a dry run never spins the tool at all.

**Framing delay: default lowered 5000 → 500 us**, applied on every connect. This
is the single biggest speed change in the project: a position read drops from
**89.8 ms to 12.5 ms** (7.2x), which speeds up the DRO, every probe point and
every streamed move. Justified by a soak, not by the sweep alone —
**500/500 reads clean, 0 corrupt** at 500 us, keeping 10x margin over the 50 us
floor where corruption starts to be a risk. `DEFAULT_FRAME_US` in
`engine/spi_probe.py` is the one place to change it.

## 7. What to run next, on the machine

1. **`spindlecal`** — settle each setpoint and compare against VPanel's own
   spindle display. Until the command/readback units are known, SPI spindle
   control is proven to *work* but not safe to *cut* with.
2. **Speed sweep again**, now the move timeout is adaptive. The default is
   19.1 mm/s; the question is whether the raw value scales it predictably.
3. **`--map-bits`**, one action at a time (lid, VPanel Pause/Resume, job start)
   to map `0x80`, `0x400`, `0x4000`, `0x01000000` and settle what `0x20` is.
4. **`--frame-soak 200`** (and lower). Only after a few hundred clean reads
   should the default framing delay come down from 5000.

Record the results in this file — the point of the audit is to replace "unused"
with "proven" or "dead", one row at a time.
