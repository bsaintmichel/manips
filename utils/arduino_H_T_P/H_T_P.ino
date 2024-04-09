/*
  Air Pressure Measurement using 2 MPX5010DP1 sensors
 * + Wire measurement setup + serial communication
 */

#include <Wire.h>
void setup() {
  #define HYT_ADDR 0x28
  Wire.begin();
  pinMode(13, OUTPUT);
  Serial.begin(115200); //9600
}

/* Lissge du bruit par moyennage sur Nlissage points  */
  #define Nlissage  10
    
/* Entrées analogiques */
  #define DP1 A0   // Sortie du capteur de pression differentiel

void loop() {

  // On initialise les sommes des valeurs analogiques lues à 0 en float pour ne pas depasser la limite int
  float SommeDP1 = 0;
  float SommeDP2 = 0;
  double humidity;
  double temperature;
  int b1;
  int b2;
  int b3;
  int b4;
  
  for (int idx=0; idx <= Nlissage; idx++){   
        SommeDP1+= float(5)/float(1023)*float(analogRead(DP1))/float(Nlissage+1);
        SommeDP2+= float(5)/float(1023)*float(analogRead(DP2))/float(Nlissage+1);
    }
  float P1 = 1000*(SommeDP1/5-0.04)/0.09;
  float P2 = 1000*(SommeDP2/5-0.04)/0.09;
  uint32_t t = millis();   
  
  // Read the bytes if they are available
  // The first two bytes are humidity the last two are temperature
  Wire.beginTransmission(HYT_ADDR);   // Begin transmission with given device on I2C bus
  Wire.requestFrom(HYT_ADDR, 4);      // Request 4 bytes 
  if(Wire.available() == 4) {   
      printf('Found wire');                
      b1 = Wire.read();
      b2 = Wire.read();
      b3 = Wire.read();
      b4 = Wire.read();
  }
  else{
    b1 = 65536;
    b2 = 65536;   // Will translate to 0% humidity and -40°C on measurements
    b3 = 65536;
    b4 = 65536;
  }

  // combine humidity bytes and calculate humidity
  int rawHumidity = b1 << 8 | b2;
  // compound bitwise to get 14 bit measurement first two bits
  // are status/stall bit (see intro text)
  rawHumidity =  (rawHumidity &= 0x3FFF);
  humidity = (100.0 / (pow(2,14)-1)) * rawHumidity;
  
  // combine temperature bytes and calculate temperature
  b4 = (b4 >> 2); // Mask away 2 least significant bits see HYT 221 doc
  
  int rawTemperature = b3 << 6 | b4;
  temperature = (165.0 / (pow(2,14)-1)) * rawTemperature - 40;
  
  Serial.print(t);
  Serial.print(" ");
  Serial.print(P1, 2);
  Serial.print(" ");
  Serial.print(P2, 2);
  Serial.print(" ");
  Serial.print(humidity, 2);
  Serial.print(" ");
  Serial.println(temperature,2);
  
  Wire.endTransmission();           // End transmission and release I2C bus
  delay(10);
  
  }
