/*
 * monoFab SRM-20 sample
 * - get system and remote status
 */

#include <SPI.h>
#include <SRM20SPIRemote.h>

SRM20SPIRemote srm20;

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
}

