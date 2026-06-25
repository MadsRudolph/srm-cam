/*
 * SRM-20 grid bed prober — drives the machine over SPI, senses contact with an
 * EXTERNAL touch probe on D7, and reports the surface Z at each grid point.
 *
 * Built on the validated single-point probe: stable position read (SPI reads are
 * flaky — never move on one read), step Z down 25 um at a time until D7 touches,
 * read Z, lift. Repeatable to the step size on this machine.
 *
 * FAST APPROACH: the first point of a run fine-steps the whole way down from the
 * datum lift (slow, but it learns where the copper is). Every point after that
 * rapids straight down to ~1 mm above the highest copper seen (APPROACH_CLEAR_UM)
 * in a single move, then fine-steps only that last millimetre. So a 2-3 mm datum
 * lift costs about the same time as a 1 mm one, with no loss of touch accuracy.
 *
 * PROBE WIRING (proven): copper board ISOLATED from the bed (paper/tape under it),
 *   D7 -> copper (floats HIGH via pull-up), GND -> collet/tool (grounded). Tool
 *   touching copper pulls D7 LOW. Spindle stays OFF the whole time.
 *
 * FRAME: the host (gerber2rml) sends probe points as LOCAL offsets (um) from a
 * datum. Operator jogs the tool ~2-3 mm above the job origin, sends 'D' to latch
 * that as the datum + safe height; then each 'P' probes datum+(x,y). The host
 * computes dz = touchZ - touchZ(origin point) for the height map.
 *
 * SERIAL PROTOCOL (115200 baud, newline-terminated, all distances in MICRONS):
 *   host -> board:
 *     D                 set datum = current X,Y and safe Z = current Z
 *     P <id> <x> <y>    probe local (x,y); rapid to datum+(x,y) at safe Z, step
 *                       down to contact, report Z, lift
 *     Z <z>             set safe Z manually (machine um)
 *     L                 lift to safe Z at current X,Y
 *     J <x> <y>         jog to absolute machine (x,y) um — lifts ~5 mm first so
 *                       XY travel never drags, then moves; replies 'J x y'
 *     T                 touch-off: descend Z from HERE until the probe contacts,
 *                       then STOP at the surface; replies 'T x y z' (um)
 *     !                 ABORT: stop any descent immediately and lift to safe Z.
 *                       Also honoured MID-probe — checked between every Z step
 *                       and whenever a move fails to complete (e.g. the lid is
 *                       opened, which pauses the machine), so it can never keep
 *                       stepping the bit down into the work.
 *     Q                 quick position query -> 'Q x y z' (um, single read)
 *     G                 get the work origin -> 'G ox oy oz' (um)
 *     O                 setOrigin TEST: shift origin Z +1 mm, report actual+origin
 *                       before/after (no motion). Then check VPanel + run R.
 *     R                 restore the origin saved by O
 *     ?                 print status
 *   board -> host:
 *     D <datX> <datY> <safeZ>          datum acknowledged
 *     R <id> <x> <y> <touchZ>          probe result (touchZ machine um)
 *     E <id> <reason>                  probe error (NOTOUCH / UNSTABLE / LOW / NODATUM)
 *     # ...                            human-readable log (host ignores)
 */
#include <SPI.h>
#include <SRM20SPIRemote.h>

SRM20SPIRemote srm20;

const int  PROBE_PIN = 7;            // external touch probe; LOW = contact
const long PROBE_STEP_UM = 25;       // fine descent step (touch accuracy)
const long PROBE_MAX_DROP_UM = 6000; // absolute floor: never drop > 6 mm from safe Z
const long OUTLIER_MARGIN_UM = 1200; // runaway guard: once a surface is known, never
                                     // descend more than this past it without contact.
                                     // A real board's surface varies far less; going
                                     // this much deeper means we missed copper.
const long APPROACH_CLEAR_UM = 1000; // FAST APPROACH: once the first point has found the
                                     // surface, rapid straight down to this height above
                                     // the highest copper seen so far, THEN fine-step.
                                     // Crosses the air gap in one move instead of ~120
                                     // tiny steps, so a 3 mm datum lift costs about the
                                     // same as 1 mm. Must exceed the board's surface
                                     // variation so the rapid never slams into copper.
const long MOVE_SPEED = -1;          // library default

long datX = 0, datY = 0, safeZ = 0;
bool haveDatum = false;

// First good touch Z = reference surface for the runaway guard above. Reset on
// every new datum ('D'), i.e. at the start of each grid run.
long refSurfaceZ = 0;
bool haveRef = false;
// Highest (least-negative) copper Z touched this run — the fast-approach planes
// its rapid descent / between-point lift just above this. Set on the first touch.
long maxSurfaceZ = 0;

// setOrigin experiment: saved origin so the test can always restore it.
long savedOX = 0, savedOY = 0, savedOZ = 0;
bool haveSavedOrigin = false;

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

// Scan any pending serial bytes for the '!' abort. Consumes them — during a
// descent we don't expect other traffic, and stopping safely wins over parsing.
bool gAbort = false;
bool checkAbort() {
  while (Serial.available()) {
    if (Serial.read() == '!') gAbort = true;
  }
  return gAbort;
}

// Wait for motion to finish. Returns FALSE if the operator aborted (!) OR the
// move never completed within the timeout — which is exactly what happens when
// the lid is opened mid-probe (the machine pauses). Callers treat false as
// "stop descending and lift", so a paused machine can never queue deeper moves.
bool waitForMotorStop() {
  unsigned long sys = 0, rem, t0 = millis();
  if (srm20.isReady()) {
    do {
      srm20.getStatus(sys, rem);
      if (checkAbort()) return false;
      delay(40);
    } while ((sys & 0x00000800) && (millis() - t0 < 8000));
    if (sys & 0x00000800) return false;        // timed out still moving -> abnormal
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

// Probe at absolute machine (mx,my). Returns 1 + touchZ on contact, 0 on no
// contact (lifted), -1 if aborted (operator '!' or a move that didn't finish),
// -2 if it ran away past the known surface (missed copper -> stopped early).
int probeAt(long mx, long my, long &touchZ) {
  // Rapid to the point at the approach height (≈1 mm above known copper once the
  // first point has found the surface; full safeZ for that first point).
  long startZ = approachZ();
  srm20.jumpTo(mx, my, startZ, MOVE_SPEED);
  if (!waitForMotorStop()) { liftSafe(mx, my); return -1; }
  if (digitalRead(PROBE_PIN) == LOW) {
    // Copper higher than the approach plane (surface rose > clearance). Back off
    // to full safe Z and fine-step from there — never plunge from a low rapid.
    srm20.jumpTo(mx, my, safeZ, MOVE_SPEED);
    if (!waitForMotorStop()) { liftSafe(mx, my); return -1; }
    if (digitalRead(PROBE_PIN) == LOW) return 0;   // touching even at safe Z: safe Z too low
    startZ = safeZ;
  }
  // Floor = absolute cap, tightened to refSurface - margin once a surface is known.
  long floorZ = safeZ - PROBE_MAX_DROP_UM;
  bool refLimited = false;
  if (haveRef) {
    long refFloor = refSurfaceZ - OUTLIER_MARGIN_UM;
    if (refFloor > floorZ) { floorZ = refFloor; refLimited = true; }
  }
  long z = startZ;
  while (z > floorZ) {
    if (checkAbort()) { liftSafe(mx, my); return -1; }
    z -= PROBE_STEP_UM;
    srm20.jumpTo(mx, my, z, MOVE_SPEED);     // X,Y fixed — Z only
    if (!waitForMotorStop()) { liftSafe(mx, my); return -1; }   // paused/aborted -> stop
    if (digitalRead(PROBE_PIN) == LOW) {
      long tx, ty, tz;
      bool ok = readPos(tx, ty, tz);
      if (ok) {
        if (!haveRef) { refSurfaceZ = tz; maxSurfaceZ = tz; haveRef = true; }  // surface ref
        else if (tz > maxSurfaceZ) maxSurfaceZ = tz;          // track highest for approach
        touchZ = tz;
      }
      liftToApproach(mx, my);                 // back up only to the approach plane
      return ok ? 1 : 0;
    }
  }
  liftSafe(mx, my);                          // hit the floor with no contact
  return refLimited ? -2 : 0;                // past the known surface -> runaway
}

// ---- tiny line reader -----------------------------------------------------
char line[48];
int  lineLen = 0;

void handleLine(char *s) {
  if (s[0] == 'D') {
    long x, y, z;
    if (!readPos(x, y, z)) { Serial.println("# datum read UNSTABLE"); return; }
    datX = x; datY = y; safeZ = z; haveDatum = true;
    haveRef = false;                         // new run -> forget the surface reference
    Serial.print("D "); Serial.print(datX); Serial.print(' ');
    Serial.print(datY); Serial.print(' '); Serial.println(safeZ);
  } else if (s[0] == 'Z') {
    safeZ = atol(s + 1);
    Serial.print("# safeZ="); Serial.println(safeZ);
  } else if (s[0] == 'L') {
    long x, y, z;
    if (readPos(x, y, z)) { srm20.jumpTo(x, y, safeZ, MOVE_SPEED); waitForMotorStop(); }
    Serial.println("# lifted");
  } else if (s[0] == 'J') {        // jog to absolute (x,y): lift ~5 mm, then travel XY
    char *p = s + 1;
    long x = strtol(p, &p, 10);
    long y = strtol(p, &p, 10);
    long cx, cy, cz;
    if (!readPos(cx, cy, cz)) { Serial.println("E J UNSTABLE"); }
    else {
      long jz = cz + 5000; if (jz > 0) jz = 0;   // 5 mm toward the top, capped at Z0
      srm20.jumpTo(cx, cy, jz, MOVE_SPEED); waitForMotorStop();   // lift in place
      srm20.jumpTo(x, y, jz, MOVE_SPEED); waitForMotorStop();     // travel XY lifted
      Serial.print("J "); Serial.print(x); Serial.print(' '); Serial.println(y);
    }
  } else if (s[0] == 'T') {        // touch-off: descend from HERE until contact, STOP
    if (digitalRead(PROBE_PIN) == LOW) { Serial.println("E T LOW"); }
    else {
      long x, y, z;
      if (!readPos(x, y, z)) { Serial.println("E T UNSTABLE"); }
      else {
        gAbort = false;                      // fresh touch-off — clear any stale abort
        long floorZ = z - PROBE_MAX_DROP_UM;
        bool hit = false, aborted = false;
        while (z > floorZ) {
          if (checkAbort()) { aborted = true; break; }
          z -= PROBE_STEP_UM;
          srm20.jumpTo(x, y, z, MOVE_SPEED);   // X,Y fixed — Z only
          if (!waitForMotorStop()) { aborted = true; break; }   // paused/aborted -> stop
          if (digitalRead(PROBE_PIN) == LOW) {
            long tx, ty, tz;
            if (readPos(tx, ty, tz)) {
              Serial.print("T "); Serial.print(tx); Serial.print(' ');
              Serial.print(ty); Serial.print(' '); Serial.println(tz);
            } else { Serial.println("E T UNSTABLE"); }
            hit = true; break;
          }
        }
        if (aborted) { liftSafe(x, y); Serial.println("E T ABORT"); }
        else if (!hit) { liftSafe(x, y); Serial.println("E T NOTOUCH"); }
      }
    }
  } else if (s[0] == 'Q') {        // fast live position + touch for the DRO
    long x, y, z;
    srm20.getActualPosition(x, y, z);
    Serial.print("Q "); Serial.print(x); Serial.print(' ');
    Serial.print(y); Serial.print(' '); Serial.print(z);
    Serial.print(' '); Serial.println(digitalRead(PROBE_PIN) == LOW ? 1 : 0);
  } else if (s[0] == 'G') {        // get work origin (read-only)
    long ox, oy, oz; srm20.getOrigin(ox, oy, oz);
    Serial.print("G "); Serial.print(ox); Serial.print(' ');
    Serial.print(oy); Serial.print(' '); Serial.println(oz);
  } else if (s[0] == 'O') {        // setOrigin TEST: shift origin Z +1 mm (no motion)
    long ax, ay, az, ox, oy, oz;
    if (!readPos(ax, ay, az)) { Serial.println("# O: pos unstable"); }
    else {
      srm20.getOrigin(ox, oy, oz);
      savedOX = ox; savedOY = oy; savedOZ = oz; haveSavedOrigin = true;
      Serial.print("# BEFORE actual "); Serial.print(ax); Serial.print(' ');
      Serial.print(ay); Serial.print(' '); Serial.print(az);
      Serial.print("   origin "); Serial.print(ox); Serial.print(' ');
      Serial.print(oy); Serial.print(' '); Serial.println(oz);
      srm20.setOrigin(ox, oy, oz + 1000);          // +1.000 mm in Z, keep X/Y
      delay(150);
      long bx, by, bz, nox, noy, noz;
      readPos(bx, by, bz);
      srm20.getOrigin(nox, noy, noz);
      Serial.print("# AFTER  actual "); Serial.print(bx); Serial.print(' ');
      Serial.print(by); Serial.print(' '); Serial.print(bz);
      Serial.print("   origin "); Serial.print(nox); Serial.print(' ');
      Serial.print(noy); Serial.print(' '); Serial.println(noz);
      Serial.println("# now read VPanel's Z; then send R to restore");
    }
  } else if (s[0] == 'R') {        // restore the origin saved by O
    if (!haveSavedOrigin) { Serial.println("# R: no saved origin (run O first)"); }
    else {
      srm20.setOrigin(savedOX, savedOY, savedOZ);
      delay(150);
      long ox, oy, oz; srm20.getOrigin(ox, oy, oz);
      Serial.print("# restored origin "); Serial.print(ox); Serial.print(' ');
      Serial.print(oy); Serial.print(' '); Serial.println(oz);
    }
  } else if (s[0] == '?') {
    long x, y, z; bool ok = readPos(x, y, z);
    Serial.print("# datum="); Serial.print(haveDatum);
    Serial.print(" safeZ="); Serial.print(safeZ);
    Serial.print(" pos="); if (ok) { Serial.print(x); Serial.print(','); Serial.print(y); Serial.print(','); Serial.println(z); }
    else Serial.println("UNSTABLE");
  } else if (s[0] == 'P') {
    char *p = s + 1;
    long id = strtol(p, &p, 10);
    long x  = strtol(p, &p, 10);
    long y  = strtol(p, &p, 10);
    if (!haveDatum) { Serial.print("E "); Serial.print(id); Serial.println(" NODATUM"); return; }
    if (digitalRead(PROBE_PIN) == LOW) { Serial.print("E "); Serial.print(id); Serial.println(" LOW"); return; }
    gAbort = false;                          // fresh probe — clear any stale abort
    long tz;
    int r = probeAt(datX + x, datY + y, tz);
    if (r == 1) {
      Serial.print("R "); Serial.print(id); Serial.print(' ');
      Serial.print(x); Serial.print(' '); Serial.print(y); Serial.print(' ');
      Serial.println(tz);
    } else if (r == -1) {
      Serial.print("E "); Serial.print(id); Serial.println(" ABORT");
    } else if (r == -2) {
      Serial.print("E "); Serial.print(id); Serial.println(" RUNAWAY");
    } else {
      Serial.print("E "); Serial.print(id); Serial.println(" NOTOUCH");
    }
  } else if (s[0] == '!') {                  // ABORT: stop and lift to safe Z
    gAbort = true;
    long x, y, z;
    if (readPos(x, y, z)) { srm20.jumpTo(x, y, safeZ, MOVE_SPEED); waitForMotorStop(); }
    Serial.println("# ABORT lifted to safe Z");
  }
}

void setup() {
  pinMode(PROBE_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  srm20.begin(9, 6);
  Serial.println("# SRM-20 grid prober ready. cmds: D | P id x y | Z z | L | ?");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) { line[lineLen] = 0; handleLine(line); lineLen = 0; }
    } else if (lineLen < (int)sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
}
