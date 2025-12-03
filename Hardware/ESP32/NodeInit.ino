#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <QMC5883LCompass.h>
#include "BluetoothSerial.h"

const int SDA_PIN = 21;
const int SCL_PIN = 22;

Adafruit_MPU6050 mpu;
QMC5883LCompass compass;
BluetoothSerial SerialBT;

const uint8_t NODE_ID = 4;
const char* BT_NAME   = "ESP32_NODE_4";

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(SDA_PIN, SCL_PIN, 400000);

  if (!mpu.begin(0x68, &Wire)) {
    Serial.println("Failed to find MPU6050!");
    while (1) delay(10);
  }

  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  compass.init();

  Serial.println("MPU6050 ready.");
  Serial.println("QMC5883L ready.");

  if (!SerialBT.begin(BT_NAME)) {
    Serial.println("Bluetooth init failed!");
    while (true) { delay(1000); }
  }

  Serial.print("Bluetooth device started, name: ");
  Serial.println(BT_NAME);
}

void sendSensorFrame() {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  compass.read();
  int mx = compass.getX();
  int my = compass.getY();
  int mz = compass.getZ();

  unsigned long t = millis();

  SerialBT.print(NODE_ID); SerialBT.print(',');
  SerialBT.print(t);        SerialBT.print(',');

  SerialBT.print(a.acceleration.x); SerialBT.print(',');
  SerialBT.print(a.acceleration.y); SerialBT.print(',');
  SerialBT.print(a.acceleration.z); SerialBT.print(',');

  SerialBT.print(g.gyro.x); SerialBT.print(',');
  SerialBT.print(g.gyro.y); SerialBT.print(',');
  SerialBT.print(g.gyro.z); SerialBT.print(',');

  SerialBT.print(mx); SerialBT.print(',');
  SerialBT.print(my); SerialBT.print(',');
  SerialBT.print(mz); SerialBT.print(',');

  SerialBT.println(temp.temperature);

  Serial.print("NODE ");
  Serial.print(NODE_ID);
  Serial.print(" -> ");
  Serial.print("t="); Serial.print(t);
  Serial.print(" ax=");
  Serial.print(a.acceleration.x);
  Serial.print(" ay=");
  Serial.print(a.acceleration.y);
  Serial.print(" az=");
  Serial.print(a.acceleration.z);
  Serial.print(" | mx=");
  Serial.print(mx);
  Serial.print(" my=");
  Serial.print(my);
  Serial.print(" mz=");
  Serial.println(mz);
}

void loop() {
  if (SerialBT.available()) {
    char cmd = SerialBT.read();

    if (cmd == 'R') { 
      sendSensorFrame();
    }
  }
  delay(1);
}
