/*
 * Remote Control Library for monoFab SRM-20 using SPI
 *
 * class name: SRM20SPIRemote
 * version   : 1.00
 *
 * Copyright (C) 2014 Roland DG Corporation All Rights Reserved.
 *
 * ---------------------------------------------------------------------------
 * LOCAL PATCH (SRM-CAM), 2026-08 — see hardware/README.md "Local patch".
 * Roland's code is untouched; the additions are marked `PATCH:` and are:
 *   1. getCommandVersion() moved private -> public (it was unreachable, so the
 *      machine's own remote-protocol version could never be read).
 *   2. rawTxRx() — a public escape hatch for probing opcodes the library does
 *      not wrap (the opcode map has gaps: 0x14+, 0x45+, 0xa5+).
 *   3. setFrameDelayUs() — the per-byte SS framing delay was a hard-coded
 *      delay(5). At 5 ms/byte a jumpTo costs ~90 ms of pure sleep, which caps
 *      move streaming at roughly 5-10 moves/s. Making it tunable lets us find
 *      the real minimum on the bench instead of guessing.
 * If you re-vendor this library from upstream, re-apply these three.
 * ---------------------------------------------------------------------------
 */

#ifndef SRM20SPIRemote_h
#define SRM20SPIRemote_h
#include <Arduino.h>

// PATCH: marker so a sketch can #ifdef the additions and still compile against
// a pristine upstream copy of this library (features degrade, build survives).
#define SRM20SPIREMOTE_LOCAL_PATCH 1

class SRM20SPIRemote
{
  int ready_pin;
  int slave_select_pin;
  unsigned int frame_delay_us;   // PATCH: was a hard-coded delay(5) in SPITxRx

public:

  bool begin(const int sspin,const int readypin);
  void end();

  bool isReady();

  void getStatus(unsigned long& system,unsigned long& remote);

  void suspendJob();
  void resumeJob();
  void cancelJob();
  void stopMoving();

  void setOrigin(long x,long y,long z);
  void jumpTo(long x,long y,long z,int movespeed);
  void turnSpindle(long rpm);
  void jumpToView(int movespeed = -1);
  void scanTo(long x,long y,long z,int scanspeed,int outspeed);

  void getActualPosition(long& x,long& y,long& z);
  unsigned long readSensor();
  void getOrigin(long& x,long& y,long& z);
  void getScanPosition(long& x,long& y,long& z);
  unsigned long getActualSpindleSpeed();

  // PATCH: was private — the only way to ask the machine what remote-command
  // version it speaks, which is our handshake that an SRM-20 is really there.
  unsigned short getCommandVersion();

  // PATCH: send one raw byte and return what came back, using the same SS
  // framing as every wrapped command. For opcode discovery on the bench ONLY —
  // an unknown opcode can move the machine. Never call it from a cut path.
  byte rawTxRx(byte tx);

  // PATCH: per-byte SS framing delay. Roland shipped 5000 us; the minimum this
  // machine actually needs is an empirical question (scripts/srm20_bench.py
  // sweeps it). AVR delayMicroseconds() tops out near 16383, so values are
  // clamped to 16000. 0 disables the delay entirely.
  void setFrameDelayUs(unsigned int us);
  unsigned int frameDelayUs();

  SRM20SPIRemote();

private:

  void setdata(unsigned short* ptr,int n);
  void setdata(unsigned long* ptr,int n);
  void getdata(unsigned short* ptr,int n);
  void getdata(unsigned long* ptr,int n);
  void requestedData(byte* buffer,char length);

  byte SPITxRx(byte tx);
};

#endif
