/*
 * monoFab SRM-20 sample
 * - get system and remote status
 */

#include <SPI.h>
#include <SRM20SPIRemote.h>

SRM20SPIRemote srm20;

long cx=0;
long cy=0;
long cz=0;
double _x,_y,_z;

void setup()
{
  Serial.begin(9600);
  srm20.begin(9,6);
}

void loop()
{
  unsigned long system,remote;

  if(srm20.isReady()){
    srm20.getStatus(system,remote);
    printstatus(system,remote);
  }

  delay(1000);
}

void printstatus(unsigned long system,unsigned long remote)
{
  char buf[32];

  sprintf(buf,"state:%d ",system & 0x00000007);
  Serial.print(buf);
  sprintf(buf,"pause:%s ",(system & 0x00000020)?"yes":"no");
  Serial.print(buf);
  sprintf(buf,"moving:%s ",(system & 0x00000800)?"yes":"no");
  Serial.print(buf);
  sprintf(buf,"spindle:%s ",(system & 0x00010000)?"on":"off");
  Serial.print(buf);
  sprintf(buf,"cover:%s ",(system & 0x00020000)?"open":"close");
  Serial.print(buf);
  sprintf(buf,"err:%s ",(system & 0x00000040)?"yes":"no");
  Serial.print(buf);
  sprintf(buf,"fatal:%s ",(system & 0x00001000)?"yes":"no");
  Serial.print(buf);
  sprintf(buf,"cmderr:%s ",(remote & 0x00000010)?"yes":"no");
  Serial.print(buf);
  Serial.print("\n");
  srm20.getActualPosition(cx,cy,cz);
  _x = cx / 1000.0;
  _y = cy / 1000.0;
  _z = cz / 1000.0;
  Serial.print(_x);
  Serial.println("mm");
  Serial.print(_y);
  Serial.println("mm");
  Serial.print(_z);
  Serial.println("mm");
  
//  Serial.println("10000");
//  srm20.turnSpindle(10000);
//  delay(3000);
//  Serial.println("5000");
//  srm20.turnSpindle(5000);
//  delay(3000);
//  srm20.turnSpindle(0);
//  Serial.println("0");
//  delay(3000);
}

