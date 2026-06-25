/*
 * SRM-20 SPI remote — VALIDATION sketch (read position + tiny test moves).
 *
 * Goal: prove, on THIS machine, that the SPI remote can (a) read X/Y/Z back and
 * (b) actually MOVE Z — the two things bed-leveling/probing depend on. One Fab
 * Academy user reported Z "just would not move" over SPI, so test that before
 * building anything.
 *
 * Hardware: Arduino (Uno/Mega) plugged into the SRM-20's SPI header behind the
 * back cover (same connection the chocolate-milling hack uses). Requires the
 * Roland `SRM20SPIRemote` library. Units are MICRONS (1/1000 mm).
 *
 * SAFETY: this commands real motion. Keep moves tiny, spindle OFF, jog the tool
 * well clear of the bed before testing 'd' (down), and keep a hand on the power
 * switch. Nothing moves until YOU send a command over the serial monitor.
 *
 * Serial commands (9600 baud, newline):
 *   p  — print actual position once (X Y Z, microns; /1000 = mm)
 *   r  — toggle continuous position streaming (~5 Hz)
 *   u  — jump Z +1.000 mm from current (UP — the safe direction; test this first)
 *   d  — jump Z -1.000 mm from current (DOWN — only with the tool clear of stock)
 *   s  — read the SRM-20's built-in sensor (readSensor) — NO motion
 *   c  — cancelJob, then read sensor (does it clear the 0x40 latch?) — NO motion
 *   m  — stopMoving, then read sensor (clear the latch?) — NO motion
 *   t  — print the external touch-probe pin state
 *
 * NOTE: the library has a native probe cycle — scanTo(x,y,z,scanspeed,outspeed)
 * drives to a target and stops on sensor contact, then getScanPosition() returns
 * where it stopped. That's our real probing path; this sketch first just proves
 * position read + Z motion + what readSensor reports. Units are MICRONS
 * (confirmed in Roland's SRMTest.ino: pos/1000.0 = mm).
 */
#include <SPI.h>
#include <SRM20SPIRemote.h>

SRM20SPIRemote srm20;

// External touch probe: tool<->copper continuity. INPUT_PULLUP, other side to
// GND -> LOW = touching. Verify the spindle isn't already grounded to Arduino
// GND (that would read touched all the time). Not driven here, just observed.
// (May be unnecessary if the SRM-20's own readSensor() does the job — test 's'.)
const int PROBE_PIN = 7;

const long STEP_UM = 1000;   // 1.000 mm test step
const long MOVE_SPEED = -1;  // matches Roland's examples (library default speed)
// scanTo speeds — UNITS UNKNOWN (Roland's confidential doc). Small + the 2 mm
// UP-only test move means even a wrong guess is harmless. Tune later.
const int SCAN_SPEED = 2;
const int OUT_SPEED  = 2;

// Auto-probe (command 'b'): step Z down until the EXTERNAL probe (D7) touches.
const long PROBE_STEP_UM = 25;     // descent step (0.025 mm) -> contact within 25 um
const long PROBE_MAX_DROP_UM = 5000; // safety floor: never drop more than 5 mm
// PROBE_PIN LOW = touch (copper on D7 floats HIGH via pull-up; grounded tool pulls it LOW)

bool streaming = false;

// SPI reads are flaky (a single getActualPosition can return garbage like 0,0,0 —
// which once sent a jumpTo to machine home/top). NEVER move on one read: require
// two consecutive reads that AGREE within a few microns. Returns false if it
// can't get a stable read, and the caller must NOT move in that case.
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

void waitForMotorStop() {
  unsigned long sys, rem;
  unsigned long t0 = millis();
  if (srm20.isReady()) {
    do {
      srm20.getStatus(sys, rem);
      delay(50);
    } while ((sys & 0x00000800) && (millis() - t0 < 8000));  // 0x800 = moving; 8 s timeout
  }
}

void printPosition() {
  long x, y, z;
  if (!readPos(x, y, z)) { Serial.println("POS read UNSTABLE"); return; }
  Serial.print("POS um  X="); Serial.print(x);
  Serial.print(" Y="); Serial.print(y);
  Serial.print(" Z="); Serial.print(z);
  Serial.print("   (mm  X="); Serial.print(x / 1000.0, 3);
  Serial.print(" Y="); Serial.print(y / 1000.0, 3);
  Serial.print(" Z="); Serial.print(z / 1000.0, 3); Serial.println(")");
}

void nudgeZ(long delta_um) {
  if (!srm20.isReady()) { Serial.println("not ready"); return; }
  long x, y, z;
  if (!readPos(x, y, z)) { Serial.println("pos read UNSTABLE — not moving"); return; }
  Serial.print("jumpTo Z "); Serial.print(z); Serial.print(" -> "); Serial.println(z + delta_um);
  srm20.jumpTo(x, y, z + delta_um, MOVE_SPEED);
  waitForMotorStop();
  printPosition();   // did Z actually change? this is the whole test
}

void setup() {
  pinMode(PROBE_PIN, INPUT_PULLUP);
  Serial.begin(9600);
  srm20.begin(9, 6);            // (slaveSelect=D9, ready=D6) — Roland's official examples
  Serial.println("SRM-20 SPI validate. cmds: p r u d s c m x z b t");
  Serial.print("isReady="); Serial.println(srm20.isReady());
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'p') printPosition();
    else if (c == 'r') { streaming = !streaming; Serial.print("stream="); Serial.println(streaming); }
    else if (c == 'u') nudgeZ(+STEP_UM);
    else if (c == 'd') nudgeZ(-STEP_UM);
    else if (c == 's') { Serial.print("readSensor="); Serial.println(srm20.readSensor()); }
    else if (c == 'c') { srm20.cancelJob(); delay(100); Serial.print("after cancelJob readSensor="); Serial.println(srm20.readSensor()); }
    else if (c == 'm') { srm20.stopMoving(); delay(100); Serial.print("after stopMoving readSensor="); Serial.println(srm20.readSensor()); }
    else if (c == 'x') {   // SAFE arming test: scanTo 2 mm UP (away from bed)
      long x, y, z; srm20.getActualPosition(x, y, z);
      Serial.print("before scanTo readSensor="); Serial.println(srm20.readSensor());
      Serial.print("scanTo UP from Z="); Serial.println(z);
      srm20.scanTo(x, y, z + 2000, SCAN_SPEED, OUT_SPEED);   // +2 mm, no contact expected
      waitForMotorStop();
      long sx, sy, sz; srm20.getScanPosition(sx, sy, sz);
      Serial.print("scanPos Z="); Serial.println(sz);
      Serial.print("after scanTo readSensor="); Serial.println(srm20.readSensor());
      printPosition();
    }
    else if (c == 'z') {   // DANGER: downward contact scan. Position the tool ~2 mm
                           // above GROUNDED copper first; finger on the power switch.
      long x, y, z; srm20.getActualPosition(x, y, z);
      Serial.print("before scanTo readSensor="); Serial.println(srm20.readSensor());
      Serial.print("scanTo DOWN from Z="); Serial.println(z);
      srm20.scanTo(x, y, z - 4000, SCAN_SPEED, OUT_SPEED);   // down at most 4 mm
      waitForMotorStop();
      long sx, sy, sz; srm20.getScanPosition(sx, sy, sz);
      Serial.print("scanPos (contact) Z="); Serial.println(sz);
      Serial.print("after scanTo readSensor="); Serial.println(srm20.readSensor());
      printPosition();
    }
    else if (c == 'b') {   // AUTO-PROBE down from current Z until D7 touches, then lift
      if (digitalRead(PROBE_PIN) == LOW) { Serial.println("already TOUCHing — lift first"); }
      else {
        long x, y, z;
        if (!readPos(x, y, z)) { Serial.println("pos read UNSTABLE — NOT probing"); }
        else {
          // X and Y are now verified — they stay FIXED; we only step Z down.
          long startZ = z, floorZ = z - PROBE_MAX_DROP_UM;
          Serial.print("probing down from X="); Serial.print(x);
          Serial.print(" Y="); Serial.print(y); Serial.print(" Z="); Serial.println(z);
          bool hit = false;
          while (z > floorZ) {
            z -= PROBE_STEP_UM;
            srm20.jumpTo(x, y, z, MOVE_SPEED);   // same X,Y every step — Z only
            waitForMotorStop();
            if (digitalRead(PROBE_PIN) == LOW) {
              long tx, ty, tz;
              if (readPos(tx, ty, tz)) {
                Serial.print("TOUCH Z="); Serial.print(tz);
                Serial.print(" ("); Serial.print(tz / 1000.0, 3); Serial.println(" mm)");
              } else {
                Serial.println("TOUCH but pos read unstable");
              }
              hit = true; break;
            }
          }
          if (!hit) Serial.println("NO touch within 5 mm — aborting");
          srm20.jumpTo(x, y, startZ, MOVE_SPEED);   // lift back to start
          waitForMotorStop();
          Serial.println("lifted");
        }
      }
    }
    else if (c == 't') { Serial.print("probe="); Serial.println(digitalRead(PROBE_PIN) == LOW ? "TOUCH" : "open"); }
  }
  if (streaming) { printPosition(); delay(200); }
}
