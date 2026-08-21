/*
 * SRM-20 grid bed prober + machine remote — drives the machine over SPI, senses
 * contact with an EXTERNAL touch probe on D7, and reports the surface Z at each
 * grid point.
 *
 * Built on the validated single-point probe: stable position read (SPI reads are
 * flaky — never move on one read), step Z down 25 um at a time until D7 touches,
 * read Z, lift. Repeatable to the step size on this machine.
 *
 * V2 accuracy upgrades:
 *   - DEBOUNCED contact: 3 consecutive LOW reads 1 ms apart, so stepper EMI
 *     flashing the probe line for a moment can't fake a touch.
 *   - TWO-STAGE TOUCH: after the 25 um coarse contact the tool lifts 150 um and
 *     re-descends at 10 um (the machine's native step). The two touches must
 *     agree within TOUCH_AGREE_UM or the point retries once and then reports
 *     E UNSTABLE — one flaky reading can no longer poison a grid point.
 *   - 'B' re-touches the datum reference so the host can measure and correct
 *     Z drift (warm-up, board settling) over a long grid run.
 *   - 'W' zeroes the work origin Z on the copper: touch, setOrigin(z=touch).
 *   - 'V' reports the firmware version + feature list so the host can adapt.
 *
 * V3 — the "retire VPanel" command set. Every one of these drives a Roland SPI
 * command the project shipped without ever calling. They are UNPROVEN on this
 * machine: the GUI's Machine test panel (and scripts/srm20_bench.py) exist to
 * find out which actually work, one at a time, before anything depends on them.
 *   - 'S <rpm>'  SPINDLE ON/OFF + RPM (turnSpindle, opcode 0x42). If this works,
 *                the "RPM is a VPanel cut-setting" limitation is gone for the
 *                SPI path. Guarded by a cover-open check and a DEADMAN: the
 *                spindle stops by itself if the host goes quiet.
 *   - 'X'        FULL STATUS (getStatus) — the raw system+remote words plus the
 *                actual spindle RPM. v2 read exactly one bit of these 64.
 *   - '~ ^ % K'  JOB CONTROL: suspend / resume / stopMoving / cancelJob. VPanel's
 *                Pause, Resume and Stop buttons.
 *   - 'Y [spd]'  jumpToView — VPanel's View button (head forward for a bit change).
 *   - 'I'        getCommandVersion — the machine's own remote-protocol version.
 *                Needs the patched library (see hardware/README.md).
 *   - 'F <us>'   set the SPI per-byte framing delay. Roland hard-coded 5 ms,
 *                which is ~90 ms of pure sleep per jumpTo and the real ceiling
 *                on move streaming. Patched library only.
 *   - 'N ...'    timed relative move — the primitive that calibrates jumpTo's
 *                speed units against mm/s.
 *   - 'A <0|1>'  arm/disarm the v3 status guard (see waitForMotorStop below).
 *
 * V3 SAFETY UPGRADE (the reason the status bits matter): v2's waitForMotorStop
 * could not tell "move finished" from "machine paused", and inferred a pause
 * from an 8-SECOND TIMEOUT — that ambiguity is what let a paused machine keep
 * queueing deeper Z moves (see docs/2026-06-25-srm20-spi-and-bed-leveling.md).
 * v3 reads the machine's own PAUSE / COVER-OPEN / FATAL bits and stops at once.
 * The bits are debounced (2 consecutive reads) because SPI reads are flaky, and
 * the whole guard can be disarmed with 'A 0' if they turn out to be unreliable
 * on this machine.
 *
 * FAST APPROACH: the first point of a run fine-steps the whole way down from the
 * datum lift (slow, but it learns where the copper is). Every point after that
 * rapids straight down to ~1 mm above the highest copper seen (APPROACH_CLEAR_UM)
 * in a single move, then fine-steps only that last millimetre.
 *
 * PROBE WIRING (proven): copper board ISOLATED from the bed (paper/tape under it),
 *   D7 -> copper (floats HIGH via pull-up), GND -> collet/tool (grounded). Tool
 *   touching copper pulls D7 LOW. Spindle stays OFF the whole time.
 *
 * FRAME: the host (gerber2rml) sends probe points as LOCAL offsets (um) from a
 * datum. Operator jogs the tool ~2-3 mm above the job origin, sends 'D' to latch
 * that as the datum + safe height; then each 'P' probes datum+(x,y).
 *
 * SERIAL PROTOCOL (115200 baud, newline-terminated, all distances in MICRONS):
 *   host -> board:
 *     D                 set datum = current X,Y and safe Z = current Z
 *     P <id> <x> <y>    probe local (x,y) -> 'R id x y z'
 *     B                 re-touch the reference (datum X,Y) -> 'B z'
 *     Z <z>             set safe Z manually (machine um)
 *     L                 lift to safe Z at current X,Y
 *     J <x> <y>         jog to absolute machine (x,y) um (lifts ~5 mm first)
 *     T                 touch-off from HERE, stop on the surface -> 'T x y z'
 *     W                 zero the work origin Z on the copper -> 'W ox oy oz'
 *     !                 ABORT: stop any descent, lift to safe Z, spindle OFF
 *     C                 begin a streaming session -> 'C ox oy oz'
 *     M <x> <y> <z> <s> stream one move to work-frame (x,y,z) um -> 'M x y z'
 *     H <x> <y>         hole test at absolute (x,y) -> 'H 1' copper / 'H 0' hole
 *     Q                 quick position query -> 'Q x y z touch'
 *     G                 get the work origin -> 'G ox oy oz'
 *     O / R             setOrigin test / restore
 *     V                 firmware version -> 'V 3 <feature,list>'
 *     ?                 print status (human readable)
 *   host -> board, NEW IN V3:
 *     X                 machine status -> 'X <system> <remote> <rpm>' (raw
 *                       32-bit words, decimal; the host owns the bit table)
 *     S <rpm>           spindle: 0 = off, else RPM -> 'S <rpm>'.
 *                       Refuses with 'E S COVER' while the lid is open.
 *                       DEADMAN: the spindle stops if no command arrives for
 *                       SPINDLE_DEADMAN_MS, so a crashed host cannot leave a
 *                       bit spinning. The host must keep talking (poll 'X').
 *     ~                 suspendJob  -> '~ ok'
 *     ^                 resumeJob   -> '^ ok'
 *     %                 stopMoving  -> '% ok'   (drop the move in flight)
 *     K                 cancelJob   -> 'K ok'
 *     Y [movespeed]     jumpToView  -> 'Y ok'   (MOVES the head)
 *     I                 command version -> 'I <ver>' / 'E I NOPATCH'
 *     F [us]            SPI framing delay -> 'F <us>' / 'E F NOPATCH'
 *     N <dx><dy><dz><s> timed relative move -> 'N <ms> <dist_um> <speed> x y z'
 *     A <0|1>           status guard on/off -> 'A <0|1>'
 *   board -> host:
 *     E <id|cmd> <reason>   error (NOTOUCH / UNSTABLE / LOW / NODATUM / ABORT /
 *                           RUNAWAY / COVER / NOPATCH / NOSESSION / CMDERR /
 *                           DEADMAN)
 *     # ...                 human-readable log (host ignores)
 */
#include <SPI.h>
#include <SRM20SPIRemote.h>

SRM20SPIRemote srm20;

const int  PROBE_PIN = 7;            // external touch probe; LOW = contact
const long PROBE_STEP_UM = 25;       // coarse descent step (finds the surface)
const long PROBE_FINE_STEP_UM = 10;  // verify descent step (machine native step)
const long RETOUCH_LIFT_UM = 150;    // lift between the coarse and fine touches
const long TOUCH_AGREE_UM = 60;      // coarse/fine agreement gate (coarse can
                                     // overshoot by up to one 25 um step; beyond
                                     // this the touch was flaky -> retry/UNSTABLE)
const long FINE_FLOOR_UM = 500;      // fine descent may go at most this far past
                                     // the coarse touch before we call it broken
const long PROBE_MAX_DROP_UM = 6000; // absolute floor: never drop > 6 mm from safe Z
const long OUTLIER_MARGIN_UM = 1200; // runaway guard: once a surface is known, never
                                     // descend more than this past it without contact.
const long APPROACH_CLEAR_UM = 1000; // FAST APPROACH clearance above known copper
const long MOVE_SPEED = -1;          // library default

// ---- v3: machine status bits. Decoded from Roland's own getStatus example
// (hardware/SRM20SPIRemote/examples/getStatus/getStatus.ino) — v2 used only
// ST_MOVING and left the other thirteen unread.
const unsigned long ST_PAUSE   = 0x00000020UL;  // paused
const unsigned long ST_MOVING  = 0x00000800UL;  // motors running
const unsigned long ST_FATAL   = 0x00001000UL;  // fatal error
const unsigned long ST_COVER   = 0x00020000UL;  // cover/lid OPEN
const unsigned long RM_CMDERR  = 0x00000010UL;  // remote word: command rejected

// Spindle: the SRM-20's rated ceiling is 7000 RPM (Roland's shared monoFab
// sample shows turnSpindle(10000), which is another model's range — clamp to
// what this machine is rated for rather than trusting the sample).
const long SPINDLE_MAX_RPM = 7000;
// If the host stops talking while the spindle is running, stop it. A crashed
// GUI, an unplugged USB cable or a closed laptop must not leave a bit spinning.
const unsigned long SPINDLE_DEADMAN_MS = 10000;
// An operator pause holds indefinitely as far as the timeout logic is
// concerned, but not literally forever: a pause nobody resumes ends as an
// abort rather than a board wedged in a loop.
const unsigned long PAUSE_MAX_MS = 300000;   // 5 minutes
// Move-wait limits. v2 used a flat 8 s, which was generous for a 25 um probe
// step and far too short for anything else: measured 2026-08-21, a 20 mm move
// at raw speed 2 outran it and came back 'E N ABORT', making the speed-unit
// calibration impossible. The timeout now measures time since motion was last
// SEEN, not total move duration, so a legitimately slow move can take as long
// as it needs while a machine that stops reporting motion is still caught.
// MOVE_MAX_MS is the backstop that keeps a stuck ST_MOVING bit from wedging
// the board forever.
const unsigned long MOVE_STALL_MS = 8000;    // no motion seen -> abnormal
const unsigned long MOVE_MAX_MS = 600000;    // 10 min absolute ceiling

long datX = 0, datY = 0, safeZ = 0;
bool haveDatum = false;

// First good touch Z = reference surface for the runaway guard above. Reset on
// every new datum ('D'), i.e. at the start of each grid run.
long refSurfaceZ = 0;
bool haveRef = false;
// Highest (least-negative) copper Z touched this run — the fast-approach planes
// its rapid descent / between-point lift just above this.
long maxSurfaceZ = 0;

// setOrigin experiment: saved origin so the test can always restore it.
long savedOX = 0, savedOY = 0, savedOZ = 0;
bool haveSavedOrigin = false;

// Streaming session ('C'/'M'): the cached work origin all moves are relative to.
long strOX = 0, strOY = 0, strOZ = 0;
bool haveStreamOrigin = false;

// ---- v3 state
long spindleRpm = 0;                 // last RPM we commanded (0 = off)
unsigned long lastCmdMs = 0;         // last complete line from the host (deadman)
bool statusGuard = true;             // honour PAUSE/COVER/FATAL in waitForMotorStop
bool sawCmdErr = false;              // the machine rejected a command (remote 0x10)

// ---- robust position read: require two agreeing reads (SPI reads can be garbage)
bool readPos(long &x, long &y, long &z) {
  long ax, ay, az, bx, by, bz;
  srm20.getActualPosition(ax, ay, az);
  for (int i = 0; i < 8; i++) {
    delay(30);
    srm20.getActualPosition(bx, by, bz);
    if (labs(ax - bx) <= 3 && labs(ay - by) <= 3 && labs(az - bz) <= 3) {
      x = bx; y = by; z = bz; return true;
    }
    ax = bx; ay = by; az = bz;
  }
  return false;
}

// Debounced contact read: stepper EMI can flash the probe line LOW for a
// moment. Real contact holds — require 3 consecutive LOW reads 1 ms apart.
bool probeTouched() {
  for (int i = 0; i < 3; i++) {
    if (digitalRead(PROBE_PIN) != LOW) return false;
    delay(1);
  }
  return true;
}

// Stop the spindle if it is running. Called on abort and by the deadman — the
// one path that must never be skipped, so it is deliberately trivial.
void spindleOff() {
  // Unconditional on purpose. The Uno resets whenever a host opens the port,
  // which zeroes spindleRpm — so a "have we got one running?" check would make
  // an abort silently decline to stop a spindle that really is turning. Sending
  // turnSpindle(0) when nothing is running costs one SPI frame and nothing else.
  srm20.turnSpindle(0);
  spindleRpm = 0;
}

// Scan any pending serial bytes for the control characters that must be obeyed
// WHILE THE MACHINE IS MOVING. Everything else is consumed and discarded —
// mid-move we don't expect other traffic, and reacting safely beats parsing.
//
// v2 only looked for '!' here, which meant a pause or a stop sent during a move
// was eaten by this drain and never reached handleLine — i.e. exactly when the
// operator needs them most, the transport commands did nothing. Each one acks
// from here too, so the host sees the same reply whether the board was busy or
// idle when it arrived.
bool gAbort = false;
bool gPauseRequested = false;    // operator pause: an expected pause, not a fault
bool checkAbort() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '!') {
      gAbort = true;
    } else if (c == '%') {                       // stopMoving: drop this move
      srm20.stopMoving();
      gAbort = true;                             // ...and stop the sequence
      Serial.println(F("% ok"));
    } else if (c == '~') {                       // pause and hold
      srm20.suspendJob();
      gPauseRequested = true;
      Serial.println(F("~ ok"));
    } else if (c == '^') {                       // resume
      srm20.resumeJob();
      gPauseRequested = false;
      Serial.println(F("^ ok"));
    }
  }
  if (gAbort) spindleOff();       // v3: an abort also kills the spindle
  return gAbort;
}

// Bits the guard treats as "stop now".
//
// COVER is PROVEN on this machine — the bit follows the lid (machine test,
// 2026-08-21). FATAL is kept as a genuine fault signal.
//
// ST_PAUSE (0x20) is deliberately NOT in here, despite Roland's example
// labelling it "pause". Measured on the machine the same day: that bit toggles
// in response to suspendJob/resumeJob/stopMoving in a way that does not match
// the label, and it can sit SET on an idle, healthy machine. With it in the
// mask the guard aborted every subsequent move — which is exactly what made the
// first machine-test run fail three motion tests in a row and report the
// spindle as dead. Guarding on a bit whose meaning is unproven is worse than
// not guarding: it breaks working probe runs. Map it first
// (scripts/srm20_bench.py --map-bits) before adding it back.
const unsigned long GUARD_MASK = ST_COVER | ST_FATAL;

// v3: does the machine's own status say something is wrong? This is what v2
// could only infer from an 8 s stall.
bool statusAbnormal(unsigned long sys) {
  return (sys & GUARD_MASK) != 0;
}

// Starting a new operation clears a stale abort AND releases an operator hold.
// Clearing the flag alone would be a trap: the machine would still be suspended
// while the firmware believed it wasn't, so the status guard would see PAUSE and
// abort the fresh operation. Resume the machine, then clear.
void clearHold() {
  gAbort = false;
  if (gPauseRequested) {
    srm20.resumeJob();
    gPauseRequested = false;
  }
}

// Stop the machine NOW.
//
// The move is queued in the Roland controller, not in this sketch, so giving up
// on WAITING for it does nothing to the machine — it carries on to the target.
// Observed 2026-08-21: a speed-calibration move the host had already declared
// failed kept driving Y across the table. Every abnormal exit from the wait
// below therefore has to halt motion, not just stop watching it. stopMoving is
// proven to work on this machine (it cut a 20 mm move short at 4.8 mm).
void haltMotion() {
  srm20.stopMoving();
}

// Wait for motion to finish. Returns FALSE if the operator aborted (!), the
// machine reports an abnormal state (v3), OR the move stalled. Every false
// return HALTS THE MACHINE first — callers treat false as "stop and lift", and
// that is only true if the original move is actually dead.
bool waitForMotorStop() {
  unsigned long sys = 0, rem = 0, t0 = millis(), pause0 = 0;
  unsigned long tStart = millis();
  int abnormal = 0;               // consecutive abnormal reads (SPI is flaky)
  if (srm20.isReady()) {
    do {
      srm20.getStatus(sys, rem);
      if (rem & RM_CMDERR) sawCmdErr = true;
      if (checkAbort()) { haltMotion(); return false; }
      // Still moving? Then nothing is stuck — restart the stall clock. This is
      // what lets a slow move run to completion instead of being cut off.
      if (sys & ST_MOVING) t0 = millis();
      if (gPauseRequested) {
        // An OPERATOR pause is not a fault: hold here without timing out and
        // without tripping the status guard (the machine is supposed to be
        // reporting PAUSE right now), until '^' resumes or the cap expires.
        if (!pause0) pause0 = millis();
        if (millis() - pause0 > PAUSE_MAX_MS) {
          gAbort = true; spindleOff(); haltMotion();
          Serial.println(F("E ~ PAUSETIMEOUT"));
          return false;
        }
        t0 = millis();
        abnormal = 0;
      } else if (statusGuard && statusAbnormal(sys)) {
        // Debounced: one garbage SPI read must not abort a good probe, but two
        // in a row is the machine genuinely telling us to stop.
        pause0 = 0;
        if (++abnormal >= 2) { gAbort = true; spindleOff(); haltMotion(); return false; }
      } else {
        pause0 = 0;
        abnormal = 0;
      }
      delay(40);
      // A held pause keeps the loop alive even once the motors have stopped —
      // otherwise a mid-move pause would be reported as a completed move.
    } while (((sys & ST_MOVING) || gPauseRequested)
             && (millis() - t0 < MOVE_STALL_MS)
             && (millis() - tStart < MOVE_MAX_MS));
    // Stalled or hit the ceiling with the motors still running: the move is
    // still live in the controller, so kill it rather than walking away.
    if (sys & ST_MOVING) { haltMotion(); return false; }
  }
  return true;
}

// Best-effort lift to safe Z (used on abort / after a probe). Never descends.
void liftSafe(long mx, long my) {
  srm20.jumpTo(mx, my, safeZ, MOVE_SPEED);
  waitForMotorStop();
}

// Travel/approach height for the fast approach: full safeZ until the surface is
// known, then just APPROACH_CLEAR_UM above the highest copper seen (capped at
// safeZ so it never rises above the operator's datum lift).
long approachZ() {
  if (!haveRef) return safeZ;
  long z = maxSurfaceZ + APPROACH_CLEAR_UM;
  return (z > safeZ) ? safeZ : z;
}

// Between-point lift after a touch: only back up to the approach plane (not the
// full datum height), so the next point's rapid + descent stays short.
void liftToApproach(long mx, long my) {
  srm20.jumpTo(mx, my, approachZ(), MOVE_SPEED);
  waitForMotorStop();
}

// Step Z down from *z* (in-out) by *step* until debounced contact or *floorZ*.
// Returns 1 on touch, 0 if the floor was reached, -1 on abort/paused-machine.
int descendUntilTouch(long mx, long my, long &z, long step, long floorZ) {
  while (z > floorZ) {
    if (checkAbort()) return -1;
    z -= step;
    srm20.jumpTo(mx, my, z, MOVE_SPEED);       // X,Y fixed — Z only
    if (!waitForMotorStop()) return -1;
    if (probeTouched()) return 1;
  }
  return 0;
}

// Verified touch at the CURRENT contact: the coarse touch at *coarseZ* is
// checked by lifting RETOUCH_LIFT_UM and re-descending at the fine step. The
// two touches must agree within TOUCH_AGREE_UM (one retry, where the first
// fine touch becomes the new reference). On success *fineZ* is the fine touch
// (machine um) and the tool is LEFT TOUCHING the surface.
// Returns 1 ok, -1 abort, -3 unstable.
int verifyTouch(long mx, long my, long coarseZ, long &fineZ) {
  long ref = coarseZ;
  for (int attempt = 0; attempt < 2; attempt++) {
    long z = ref + RETOUCH_LIFT_UM;
    if (z > safeZ) z = safeZ;
    srm20.jumpTo(mx, my, z, MOVE_SPEED);
    if (!waitForMotorStop()) return -1;
    int r = descendUntilTouch(mx, my, z, PROBE_FINE_STEP_UM, ref - FINE_FLOOR_UM);
    if (r == -1) return -1;
    if (r != 1) return -3;                     // lost the surface on re-descend
    long tx, ty, tz;
    if (!readPos(tx, ty, tz)) return -3;
    if (labs(tz - ref) <= TOUCH_AGREE_UM) { fineZ = tz; return 1; }
    ref = tz;                                  // disagreed: trust the fine touch, retry
  }
  return -3;
}

// Probe at absolute machine (mx,my). Returns 1 + touchZ on verified contact,
// 0 on no contact (lifted), -1 if aborted, -2 if it ran away past the known
// surface, -3 if the two touches wouldn't agree.
int probeAt(long mx, long my, long &touchZ) {
  long startZ = approachZ();
  srm20.jumpTo(mx, my, startZ, MOVE_SPEED);
  if (!waitForMotorStop()) { liftSafe(mx, my); return -1; }
  if (probeTouched()) {
    // Copper higher than the approach plane (surface rose > clearance). Back off
    // to full safe Z and fine-step from there — never plunge from a low rapid.
    srm20.jumpTo(mx, my, safeZ, MOVE_SPEED);
    if (!waitForMotorStop()) { liftSafe(mx, my); return -1; }
    if (probeTouched()) return 0;              // touching even at safe Z: safe Z too low
    startZ = safeZ;
  }
  long floorZ = safeZ - PROBE_MAX_DROP_UM;
  bool refLimited = false;
  if (haveRef) {
    long refFloor = refSurfaceZ - OUTLIER_MARGIN_UM;
    if (refFloor > floorZ) { floorZ = refFloor; refLimited = true; }
  }
  long z = startZ;
  int r = descendUntilTouch(mx, my, z, PROBE_STEP_UM, floorZ);
  if (r == -1) { liftSafe(mx, my); return -1; }
  if (r == 0)  { liftSafe(mx, my); return refLimited ? -2 : 0; }
  long cx, cy, cz;
  long coarseZ = z;                            // fall back to the commanded Z...
  if (readPos(cx, cy, cz)) coarseZ = cz;       // ...but prefer the encoder read
  long fineZ;
  r = verifyTouch(mx, my, coarseZ, fineZ);
  if (r == -1) { liftSafe(mx, my); return -1; }
  if (r != 1)  { liftSafe(mx, my); return -3; }
  if (!haveRef) { refSurfaceZ = fineZ; maxSurfaceZ = fineZ; haveRef = true; }
  else if (fineZ > maxSurfaceZ) maxSurfaceZ = fineZ;
  touchZ = fineZ;
  liftToApproach(mx, my);                      // back up only to the approach plane
  return 1;
}

// Touch-off from the CURRENT position (no datum needed): coarse descent, then
// the same two-stage verification, ending ON the surface. Returns 1 + touch
// position, 0 no contact, -1 abort, -3 unstable. Used by 'T' and 'W'.
int touchOffHere(long &tx, long &ty, long &tz) {
  long x, y, z;
  if (!readPos(x, y, z)) return -3;
  long topZ = z;                               // where the descent started
  long floorZ = z - PROBE_MAX_DROP_UM;
  int r = descendUntilTouch(x, y, z, PROBE_STEP_UM, floorZ);
  if (r != 1) return r;                        // 0 no-touch / -1 abort
  long coarseZ = z;
  { long ax, ay, az; if (readPos(ax, ay, az)) coarseZ = az; }
  long saveSafe = safeZ;
  safeZ = topZ;                                // verifyTouch caps its lift at safeZ
  long fineZ;
  r = verifyTouch(x, y, coarseZ, fineZ);
  safeZ = saveSafe;
  if (r != 1) return r;
  long ax, ay, az;
  if (!readPos(ax, ay, az)) return -3;
  tx = ax; ty = ay; tz = az;
  return 1;
}

// ---- tiny line reader -----------------------------------------------------
char line[48];
int  lineLen = 0;

void handleLine(char *s) {
  if (s[0] == 'D') {
    long x, y, z;
    if (!readPos(x, y, z)) { Serial.println(F("# datum read UNSTABLE")); return; }
    datX = x; datY = y; safeZ = z; haveDatum = true;
    haveRef = false;                         // new run -> forget the surface reference
    Serial.print(F("D ")); Serial.print(datX); Serial.print(' ');
    Serial.print(datY); Serial.print(' '); Serial.println(safeZ);
  } else if (s[0] == 'Z') {
    safeZ = atol(s + 1);
    Serial.print(F("# safeZ=")); Serial.println(safeZ);
  } else if (s[0] == 'L') {
    long x, y, z;
    if (readPos(x, y, z)) { srm20.jumpTo(x, y, safeZ, MOVE_SPEED); waitForMotorStop(); }
    Serial.println(F("# lifted"));
  } else if (s[0] == 'J') {        // jog to absolute (x,y): lift ~5 mm, then travel XY
    char *p = s + 1;
    long x = strtol(p, &p, 10);
    long y = strtol(p, &p, 10);
    long cx, cy, cz;
    if (!readPos(cx, cy, cz)) { Serial.println(F("E J UNSTABLE")); }
    else {
      long jz = cz + 5000; if (jz > 0) jz = 0;   // 5 mm toward the top, capped at Z0
      srm20.jumpTo(cx, cy, jz, MOVE_SPEED); waitForMotorStop();   // lift in place
      srm20.jumpTo(x, y, jz, MOVE_SPEED); waitForMotorStop();     // travel XY lifted
      Serial.print(F("J ")); Serial.print(x); Serial.print(' '); Serial.println(y);
    }
  } else if (s[0] == 'T') {        // touch-off: descend from HERE, STOP at surface
    if (probeTouched()) { Serial.println(F("E T LOW")); return; }
    clearHold();                          // fresh touch-off — clear any stale abort
    long tx, ty, tz;
    int r = touchOffHere(tx, ty, tz);
    if (r == 1) {
      Serial.print(F("T ")); Serial.print(tx); Serial.print(' ');
      Serial.print(ty); Serial.print(' '); Serial.println(tz);
    } else if (r == -1) {
      long x, y, z; if (readPos(x, y, z)) liftSafe(x, y);
      Serial.println(F("E T ABORT"));
    } else if (r == -3) {
      Serial.println(F("E T UNSTABLE"));
    } else {
      long x, y, z; if (readPos(x, y, z)) liftSafe(x, y);
      Serial.println(F("E T NOTOUCH"));
    }
  } else if (s[0] == 'W') {        // zero the work-origin Z on the copper
    if (probeTouched()) { Serial.println(F("E W LOW")); return; }
    clearHold();
    long tx, ty, tz;
    int r = touchOffHere(tx, ty, tz);
    if (r != 1) {
      if (r == -1) { long x, y, z; if (readPos(x, y, z)) liftSafe(x, y); }
      if (r == -1)      Serial.println(F("E W ABORT"));
      else if (r == -3) Serial.println(F("E W UNSTABLE"));
      else              Serial.println(F("E W NOTOUCH"));
      return;
    }
    long ox, oy, oz;
    srm20.getOrigin(ox, oy, oz);
    srm20.setOrigin(ox, oy, tz);             // origin Z = the copper surface
    delay(150);
    long nox, noy, noz;
    srm20.getOrigin(nox, noy, noz);
    srm20.jumpTo(tx, ty, tz + 2000, MOVE_SPEED);   // lift 2 mm clear of the surface
    waitForMotorStop();
    Serial.print(F("W ")); Serial.print(nox); Serial.print(' ');
    Serial.print(noy); Serial.print(' '); Serial.println(noz);
    Serial.println(F("# origin Z zeroed on copper (User CS - verify G54 once)"));
  } else if (s[0] == 'B') {        // re-touch the reference (datum XY) for drift
    if (!haveDatum) { Serial.println(F("E B NODATUM")); return; }
    if (probeTouched()) { Serial.println(F("E B LOW")); return; }
    clearHold();
    long tz;
    int r = probeAt(datX, datY, tz);
    if (r == 1) { Serial.print(F("B ")); Serial.println(tz); }
    else if (r == -1) Serial.println(F("E B ABORT"));
    else if (r == -2) Serial.println(F("E B RUNAWAY"));
    else if (r == -3) Serial.println(F("E B UNSTABLE"));
    else              Serial.println(F("E B NOTOUCH"));
  } else if (s[0] == 'Q') {        // fast live position + touch for the DRO
    long x, y, z;
    srm20.getActualPosition(x, y, z);
    Serial.print(F("Q ")); Serial.print(x); Serial.print(' ');
    Serial.print(y); Serial.print(' '); Serial.print(z);
    Serial.print(' '); Serial.println(digitalRead(PROBE_PIN) == LOW ? 1 : 0);
  } else if (s[0] == 'G') {        // get work origin (read-only)
    long ox, oy, oz; srm20.getOrigin(ox, oy, oz);
    Serial.print(F("G ")); Serial.print(ox); Serial.print(' ');
    Serial.print(oy); Serial.print(' '); Serial.println(oz);
  } else if (s[0] == 'X') {        // v3: FULL machine status, raw words + RPM.
    // The host owns the bit table (one source of truth, and the meanings are
    // still being confirmed on this machine) — the firmware just forwards.
    unsigned long sys = 0, rem = 0;
    srm20.getStatus(sys, rem);
    unsigned long rpm = srm20.getActualSpindleSpeed();
    if (rem & RM_CMDERR) sawCmdErr = true;
    Serial.print(F("X ")); Serial.print(sys); Serial.print(' ');
    Serial.print(rem); Serial.print(' '); Serial.println(rpm);
  } else if (s[0] == 'S') {        // v3: SPINDLE — 'S 0' off, 'S <rpm>' on
    long rpm = atol(s + 1);
    if (rpm < 0) rpm = 0;
    if (rpm > SPINDLE_MAX_RPM) rpm = SPINDLE_MAX_RPM;
    if (rpm > 0) {
      // Never start a bit spinning with the lid open, or resting on the copper
      // with the probe clips attached.
      unsigned long sys = 0, rem = 0;
      srm20.getStatus(sys, rem);
      if (statusGuard && (sys & ST_COVER)) { Serial.println(F("E S COVER")); return; }
      if (probeTouched()) { Serial.println(F("E S LOW")); return; }
    }
    srm20.turnSpindle(rpm);
    spindleRpm = rpm;
    Serial.print(F("S ")); Serial.println(rpm);
  } else if (s[0] == '~') {        // v3: suspendJob (VPanel Pause)
    // Reached only when the board was IDLE — mid-move these arrive through
    // checkAbort() instead, which acks identically. The flag is set in both
    // paths so a pause issued before a move still holds that move.
    srm20.suspendJob();
    gPauseRequested = true;
    Serial.println(F("~ ok"));
  } else if (s[0] == '^') {        // v3: resumeJob (VPanel Resume)
    srm20.resumeJob();
    gPauseRequested = false;
    Serial.println(F("^ ok"));
  } else if (s[0] == '%') {        // v3: stopMoving — drop the move in flight.
    srm20.stopMoving();
    Serial.println(F("% ok"));
  } else if (s[0] == 'K') {        // v3: cancelJob (VPanel Stop)
    srm20.cancelJob();
    gPauseRequested = false;
    spindleOff();
    Serial.println(F("K ok"));
  } else if (s[0] == 'Y') {        // v3: jumpToView — MOVES the head forward
    long sp = (s[1] == 0) ? MOVE_SPEED : atol(s + 1);
    srm20.jumpToView((int)sp);
    waitForMotorStop();
    Serial.println(F("Y ok"));
  } else if (s[0] == 'I') {        // v3: the machine's remote-command version
#ifdef SRM20SPIREMOTE_LOCAL_PATCH
    unsigned short v = srm20.getCommandVersion();
    Serial.print(F("I ")); Serial.println(v);
#else
    Serial.println(F("E I NOPATCH"));
#endif
  } else if (s[0] == 'F') {        // v3: SPI per-byte framing delay (us)
#ifdef SRM20SPIREMOTE_LOCAL_PATCH
    if (s[1] != 0) srm20.setFrameDelayUs((unsigned int)atol(s + 1));
    Serial.print(F("F ")); Serial.println(srm20.frameDelayUs());
#else
    Serial.println(F("E F NOPATCH"));
#endif
  } else if (s[0] == 'N') {        // v3: TIMED relative move — calibrates the
    // speed units. Timed on the board (millis) so the USB round-trip is not in
    // the number. Resolution is the status-poll interval (~100 ms at the stock
    // framing delay), so use moves of several seconds.
    char *p = s + 1;
    long dx = strtol(p, &p, 10);
    long dy = strtol(p, &p, 10);
    long dz = strtol(p, &p, 10);
    long sp = strtol(p, &p, 10);
    long x, y, z;
    if (!readPos(x, y, z)) { Serial.println(F("E N UNSTABLE")); return; }
    clearHold();
    long tz = z + dz; if (tz > 0) tz = 0;       // never above machine Z home
    unsigned long t0 = millis();
    srm20.jumpTo(x + dx, y + dy, tz, (int)sp);
    bool ok = waitForMotorStop();
    unsigned long ms = millis() - t0;
    long ax, ay, az;
    if (!readPos(ax, ay, az)) { ax = x + dx; ay = y + dy; az = tz; }
    float fx = (float)(ax - x), fy = (float)(ay - y), fz = (float)(az - z);
    long dist = (long)sqrt(fx * fx + fy * fy + fz * fz);
    if (!ok) { Serial.println(F("E N ABORT")); return; }
    Serial.print(F("N ")); Serial.print(ms); Serial.print(' ');
    Serial.print(dist); Serial.print(' '); Serial.print(sp); Serial.print(' ');
    Serial.print(ax); Serial.print(' '); Serial.print(ay); Serial.print(' ');
    Serial.println(az);
  } else if (s[0] == 'A') {        // v3: arm/disarm the status guard
    if (s[1] != 0) statusGuard = (atol(s + 1) != 0);
    Serial.print(F("A ")); Serial.println(statusGuard ? 1 : 0);
  } else if (s[0] == 'O') {        // setOrigin TEST: shift origin Z +1 mm (no motion)
    long ax, ay, az, ox, oy, oz;
    if (!readPos(ax, ay, az)) { Serial.println(F("# O: pos unstable")); }
    else {
      srm20.getOrigin(ox, oy, oz);
      savedOX = ox; savedOY = oy; savedOZ = oz; haveSavedOrigin = true;
      Serial.print(F("# BEFORE actual ")); Serial.print(ax); Serial.print(' ');
      Serial.print(ay); Serial.print(' '); Serial.print(az);
      Serial.print(F("   origin ")); Serial.print(ox); Serial.print(' ');
      Serial.print(oy); Serial.print(' '); Serial.println(oz);
      srm20.setOrigin(ox, oy, oz + 1000);          // +1.000 mm in Z, keep X/Y
      delay(150);
      long bx, by, bz, nox, noy, noz;
      readPos(bx, by, bz);
      srm20.getOrigin(nox, noy, noz);
      Serial.print(F("# AFTER  actual ")); Serial.print(bx); Serial.print(' ');
      Serial.print(by); Serial.print(' '); Serial.print(bz);
      Serial.print(F("   origin ")); Serial.print(nox); Serial.print(' ');
      Serial.print(noy); Serial.print(' '); Serial.println(noz);
      Serial.println(F("# now read VPanel's Z; then send R to restore"));
    }
  } else if (s[0] == 'R') {        // restore the origin saved by O
    if (!haveSavedOrigin) { Serial.println(F("# R: no saved origin (run O first)")); }
    else {
      srm20.setOrigin(savedOX, savedOY, savedOZ);
      delay(150);
      long ox, oy, oz; srm20.getOrigin(ox, oy, oz);
      Serial.print(F("# restored origin ")); Serial.print(ox); Serial.print(' ');
      Serial.print(oy); Serial.print(' '); Serial.println(oz);
    }
  } else if (s[0] == 'C') {        // begin a streaming session: cache the work
    // origin (all 'M' moves are origin-relative) and clear any stale abort
    clearHold();
    sawCmdErr = false;
    srm20.getOrigin(strOX, strOY, strOZ);
    haveStreamOrigin = true;
    Serial.print(F("C ")); Serial.print(strOX); Serial.print(' ');
    Serial.print(strOY); Serial.print(' '); Serial.println(strOZ);
  } else if (s[0] == 'M') {        // EXPERIMENTAL stream move: work-frame um
    if (!haveStreamOrigin) { Serial.println(F("E M NOSESSION")); return; }
    if (checkAbort()) { Serial.println(F("E M ABORT")); return; }
    char *p = s + 1;
    long x = strtol(p, &p, 10);
    long y = strtol(p, &p, 10);
    long z = strtol(p, &p, 10);
    long sp = strtol(p, &p, 10);
    long mz = strOZ + z;
    if (mz > 0) mz = 0;            // never above machine Z home
    sawCmdErr = false;
    srm20.jumpTo(strOX + x, strOY + y, mz, (int)sp);
    if (!waitForMotorStop()) { Serial.println(F("E M ABORT")); return; }
    // v3: the machine can REJECT a command (remote word bit 0x10). v2 never
    // looked, so a refused move was acked as if it had run.
    if (sawCmdErr) { sawCmdErr = false; Serial.println(F("E M CMDERR")); return; }
    Serial.print(F("M ")); Serial.print(x); Serial.print(' ');
    Serial.print(y); Serial.print(' '); Serial.println(z);
  } else if (s[0] == 'H') {        // hole test at absolute (x,y) um
    if (!haveRef) { Serial.println(F("E H NOREF")); return; }
    if (probeTouched()) { Serial.println(F("E H LOW")); return; }
    clearHold();
    char *p = s + 1;
    long x = strtol(p, &p, 10);
    long y = strtol(p, &p, 10);
    long startZ = approachZ();
    srm20.jumpTo(x, y, startZ, MOVE_SPEED);
    if (!waitForMotorStop()) { liftSafe(x, y); Serial.println(F("E H ABORT")); return; }
    long z = startZ;
    int r = descendUntilTouch(x, y, z, PROBE_STEP_UM,
                              refSurfaceZ - 200);   // 0.2 mm past the surface
    if (r == -1) { liftSafe(x, y); Serial.println(F("E H ABORT")); return; }
    liftToApproach(x, y);
    Serial.println(r == 1 ? F("H 1") : F("H 0"));
  } else if (s[0] == 'V') {        // version + feature flags for the host
#ifdef SRM20SPIREMOTE_LOCAL_PATCH
    Serial.println(F("V 3 probe,refine,verify,retouch,zeroz,touchbit,stream,"
                     "holetest,status,spindle,jobctl,view,timedmove,guard,info,frame"));
#else
    Serial.println(F("V 3 probe,refine,verify,retouch,zeroz,touchbit,stream,"
                     "holetest,status,spindle,jobctl,view,timedmove,guard"));
#endif
  } else if (s[0] == '?') {
    long x, y, z; bool ok = readPos(x, y, z);
    Serial.print(F("# v3 datum=")); Serial.print(haveDatum);
    Serial.print(F(" safeZ=")); Serial.print(safeZ);
    Serial.print(F(" rpm=")); Serial.print(spindleRpm);
    Serial.print(F(" guard=")); Serial.print(statusGuard);
    Serial.print(F(" pos="));
    if (ok) { Serial.print(x); Serial.print(','); Serial.print(y); Serial.print(','); Serial.println(z); }
    else Serial.println(F("UNSTABLE"));
  } else if (s[0] == 'P') {
    char *p = s + 1;
    long id = strtol(p, &p, 10);
    long x  = strtol(p, &p, 10);
    long y  = strtol(p, &p, 10);
    if (!haveDatum) { Serial.print(F("E ")); Serial.print(id); Serial.println(F(" NODATUM")); return; }
    if (probeTouched()) { Serial.print(F("E ")); Serial.print(id); Serial.println(F(" LOW")); return; }
    clearHold();                          // fresh probe — clear any stale abort
    long tz;
    int r = probeAt(datX + x, datY + y, tz);
    if (r == 1) {
      Serial.print(F("R ")); Serial.print(id); Serial.print(' ');
      Serial.print(x); Serial.print(' '); Serial.print(y); Serial.print(' ');
      Serial.println(tz);
    } else if (r == -1) {
      Serial.print(F("E ")); Serial.print(id); Serial.println(F(" ABORT"));
    } else if (r == -2) {
      Serial.print(F("E ")); Serial.print(id); Serial.println(F(" RUNAWAY"));
    } else if (r == -3) {
      Serial.print(F("E ")); Serial.print(id); Serial.println(F(" UNSTABLE"));
    } else {
      Serial.print(F("E ")); Serial.print(id); Serial.println(F(" NOTOUCH"));
    }
  } else if (s[0] == '!') {                  // ABORT: stop, spindle off, lift
    gAbort = true;
    spindleOff();
    // v3: stopMoving first so a long move in flight is dropped instead of
    // having to finish before the lift can even be commanded.
    srm20.stopMoving();
    // A suspended machine will not execute the lift below, and the hold flag
    // would make waitForMotorStop sit there waiting for a resume that is never
    // coming. Release the hold so the abort can actually retract the tool.
    if (gPauseRequested) { srm20.resumeJob(); gPauseRequested = false; }
    long x, y, z;
    if (readPos(x, y, z)) { srm20.jumpTo(x, y, safeZ, MOVE_SPEED); waitForMotorStop(); }
    Serial.println(F("# ABORT lifted to safe Z, spindle off"));
  }
}

void setup() {
  pinMode(PROBE_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  srm20.begin(9, 6);
  lastCmdMs = millis();
  // NOTE: deliberately does NOT touch a spindle that is already running.
  // The Uno resets whenever a host opens the port, and the operator drives the
  // spindle from VPanel interactively — adopting it into the deadman (or just
  // turning it off here) would stop their spindle ten seconds after SRM-CAM
  // connects, or mid-cut during a VPanel job. The deadman's job is narrow: if
  // WE started the spindle and OUR host goes quiet, stop it. A spindle someone
  // else started is not ours to police.
  Serial.println(F("# SRM-20 prober v3 ready. D|P id x y|B|T|W|X|S rpm|~^%K|Y|N|V|?"));
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) {
        line[lineLen] = 0;
        lastCmdMs = millis();      // the host is alive -> feed the deadman
        handleLine(line);
        lineLen = 0;
      }
    } else if (lineLen < (int)sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
  // SPINDLE DEADMAN: a running spindle with a silent host is the one failure
  // mode of SPI spindle control that can hurt someone. Stop it.
  if (spindleRpm != 0 && (millis() - lastCmdMs) > SPINDLE_DEADMAN_MS) {
    spindleOff();
    Serial.println(F("E S DEADMAN"));
  }
}
