/*
 * Remote Control Library for monoFab SRM-20 using SPI
 *
 * class name: SRM20SPIRemote
 * version   : 1.00
 *
 * Copyright (C) 2014 Roland DG Corporation All Rights Reserved.
 */

#ifndef SRM20SPIRemote_h
#define SRM20SPIRemote_h
#include <Arduino.h>

class SRM20SPIRemote
{
  int ready_pin;
  int slave_select_pin;

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

  SRM20SPIRemote();

private:

  void setdata(unsigned short* ptr,int n);
  void setdata(unsigned long* ptr,int n);
  void getdata(unsigned short* ptr,int n);
  void getdata(unsigned long* ptr,int n);
  void requestedData(byte* buffer,char length);
  unsigned short getCommandVersion();

  byte SPITxRx(byte tx);
};

#endif
