/*
 * Remote Control Library for monoFab SRM-20 using SPI
 *
 * class name: SRM20SPIRemote
 * version   : 1.00
 *
 * Copyright (C) 2014 Roland DG Corporation All Rights Reserved.
 */

#include <Arduino.h>
#include <SPI.h>
#include "SRM20SPIRemote.h"

SRM20SPIRemote::SRM20SPIRemote()
{
}

bool SRM20SPIRemote::begin(const int sspin,const int readypin)
{
  ready_pin = readypin;
  slave_select_pin = sspin;

  pinMode(ready_pin,INPUT);
  pinMode(slave_select_pin,OUTPUT);
  digitalWrite(slave_select_pin,LOW);

  SPI.begin();
  SPI.setBitOrder(MSBFIRST);
  SPI.setDataMode(SPI_MODE0);
  SPI.setClockDivider(SPI_CLOCK_DIV4);

  return true;
}

void SRM20SPIRemote::end()
{
  digitalWrite(slave_select_pin,LOW);
  SPI.end();
}

bool SRM20SPIRemote::isReady()
{
  return digitalRead(ready_pin) == HIGH;
}

void SRM20SPIRemote::getStatus(unsigned long& system,unsigned long& remote)
{
  byte buf[4*2];
  byte* p = buf;
  int n = sizeof(buf);

  SPITxRx(0x01);
  SPITxRx(0x08);
  SPITxRx(0x00);

  while(0 < n--){
    *p++ = SPITxRx(0x00);
  }

  memcpy(&system,&buf[0],4);
  memcpy(&remote,&buf[4],4);
}

unsigned short SRM20SPIRemote::getCommandVersion()
{
  byte verh,verl,buf[2];
  unsigned short version,pattern;

  SPITxRx(0x02);
  SPITxRx(0x04);
  SPITxRx(0x00);

  verh = SPITxRx(0x00);
  verl = SPITxRx(0x00);
  version = ((unsigned short)verh << 8) | (unsigned short)verl;

  buf[0] = SPITxRx(0x00);
  buf[1] = SPITxRx(0x00);
  memcpy(&pattern,&buf[0],2);

  return version;
}

void SRM20SPIRemote::requestedData(byte* buffer,char length)
{
  byte* p = buffer;

  SPITxRx(0x03);
  SPITxRx(length);
  SPITxRx(0x00);

  while(0 < length--){
    *p++ = SPITxRx(0x00);
  }
}

void SRM20SPIRemote::suspendJob()
{
  SPITxRx(0x10);
  SPITxRx(0x00);
}

void SRM20SPIRemote::resumeJob()
{
  SPITxRx(0x11);
  SPITxRx(0x00);
}

void SRM20SPIRemote::cancelJob()
{
  SPITxRx(0x12);
  SPITxRx(0x00);
}

void SRM20SPIRemote::stopMoving()
{
  SPITxRx(0x13);
  SPITxRx(0x00);
}

void SRM20SPIRemote::setOrigin(long x,long y,long z)
{
  unsigned long lval[3];

  lval[0] = x;
  lval[1] = y;
  lval[2] = z;

  SPITxRx(0x40);
  SPITxRx(0x0c);
  setdata(lval,3);
}

void SRM20SPIRemote::jumpTo(long x,long y,long z,int movespeed)
{
  unsigned short sval[2];
  unsigned long  lval[3];

  sval[0] = movespeed;
  sval[1] = 0;
  lval[0] = x;
  lval[1] = y;
  lval[2] = z;

  SPITxRx(0x41);
  SPITxRx(0x10);
  setdata(sval,2);
  setdata(lval,3);
}

void SRM20SPIRemote::turnSpindle(long rpm)
{
  SPITxRx(0x42);
  SPITxRx(0x04);
  setdata((unsigned long*)&rpm,1);
}

void SRM20SPIRemote::jumpToView(int movespeed)
{
  SPITxRx(0x43);
  SPITxRx(0x02);
  setdata((unsigned short*)&movespeed,1);
}

void SRM20SPIRemote::scanTo(long x,long y,long z,int scanspeed,int outspeed)
{
  unsigned short sval[2];
  unsigned long  lval[3];

  sval[0] = scanspeed;
  sval[1] = outspeed;
  lval[0] = x;
  lval[1] = y;
  lval[2] = z;

  SPITxRx(0x44);
  SPITxRx(0x10);
  setdata(sval,2);
  setdata(lval,3);
}

void SRM20SPIRemote::getActualPosition(long& x,long& y,long& z)
{
  unsigned long lval[3];

  SPITxRx(0xa0);
  SPITxRx(0x00);

  getdata(lval,3);
  x = lval[0];
  y = lval[1];
  z = lval[2];
}

unsigned long SRM20SPIRemote::readSensor()
{
  unsigned long lval;

  SPITxRx(0xa1);
  SPITxRx(0x00);

  getdata(&lval,1);
  return lval;
}

void SRM20SPIRemote::getOrigin(long& x,long& y,long& z)
{
  unsigned long lval[3];

  SPITxRx(0xa2);
  SPITxRx(0x00);

  getdata(lval,3);
  x = lval[0];
  y = lval[1];
  z = lval[2];
}

void SRM20SPIRemote::getScanPosition(long& x,long& y,long& z)
{
  unsigned long lval[3];

  SPITxRx(0xa3);
  SPITxRx(0x00);

  getdata(lval,3);
  x = lval[0];
  y = lval[1];
  z = lval[2];
}

unsigned long SRM20SPIRemote::getActualSpindleSpeed()
{
  unsigned long lval;

  SPITxRx(0xa4);
  SPITxRx(0x00);

  getdata(&lval,1);
  return lval;
}

//////////////////////////////////////////////////////////////////////

void SRM20SPIRemote::setdata(unsigned short* ptr,int n)
{
  int i = n * sizeof(*ptr);
  byte* p = (byte*)ptr;

  while(0 < i--){
    SPITxRx(*p++);
  }
}

void SRM20SPIRemote::setdata(unsigned long* ptr,int n)
{
  int i = n * sizeof(*ptr);
  byte* p = (byte*)ptr;

  while(0 < i--){
    SPITxRx(*p++);
  }
}

void SRM20SPIRemote::getdata(unsigned short* ptr,int n)
{
  requestedData((byte*)ptr,n*sizeof(*ptr));
}

void SRM20SPIRemote::getdata(unsigned long* ptr,int n)
{
  requestedData((byte*)ptr,n*sizeof(*ptr));
}

byte SRM20SPIRemote::SPITxRx(byte tx)
{
  byte rx;
  digitalWrite(slave_select_pin,LOW);
  delay(5);
  rx = SPI.transfer(tx);
  digitalWrite(slave_select_pin,HIGH);
  return rx;
}
