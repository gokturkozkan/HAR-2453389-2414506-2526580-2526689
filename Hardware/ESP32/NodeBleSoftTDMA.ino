#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <NimBLEDevice.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <math.h>
#include <string>

const int SDA_PIN = 21;
const int SCL_PIN = 22;

const uint8_t NODE_ID = 4;
const char* DEVICE_NAME = "ESP32_NODE_4";

const char* HAR_SERVICE_UUID = "8c3a1000-7f8f-4f4a-9a91-0c2f83dd0001";
const char* CONTROL_CHAR_UUID = "8c3a1001-7f8f-4f4a-9a91-0c2f83dd0001";
const char* STREAM_CHAR_UUID = "8c3a1002-7f8f-4f4a-9a91-0c2f83dd0001";

const char PACKET_MAGIC[4] = {'H', 'A', 'R', 'B'};
const uint8_t PROTOCOL_VERSION = 1;
const uint8_t PACKET_TYPE_HELLO = 1;
const uint8_t PACKET_TYPE_SYNC = 2;
const uint8_t PACKET_TYPE_DATA = 3;
const uint16_t HELLO_FLAG_SYNC_LOCKED = 1 << 0;

const uint32_t SAMPLE_PERIOD_US = 40000;
const uint16_t SUPERFRAME_MS = 280;
const uint16_t SYNC_LEAD_MS = 20;
const uint16_t NODE_SLOT_MS = 40;
const uint16_t RING_BUFFER_CAPACITY = 256;
const uint16_t PREFERRED_ATT_MTU = 185;
const uint16_t ATT_PAYLOAD_BYTES = PREFERRED_ATT_MTU - 3;
const uint16_t DATA_PREFIX_BYTES = 16;
const uint16_t SAMPLE_BYTES = 12;
const uint8_t MAX_SAMPLES_PER_PACKET = (ATT_PAYLOAD_BYTES - DATA_PREFIX_BYTES) / SAMPLE_BYTES;
const uint8_t MAX_PACKETS_PER_SLOT = 4;
const uint32_t SYNC_TIMEOUT_US = 3UL * SUPERFRAME_MS * 1000UL;
const uint32_t HELLO_INTERVAL_US = 1000000UL;
const uint32_t FIRMWARE_VERSION = 1;

Adafruit_MPU6050 mpu;
NimBLECharacteristic* controlCharacteristic = nullptr;
NimBLECharacteristic* streamCharacteristic = nullptr;

struct ImuSample {
  uint32_t seq;
  uint64_t tUs;
  int16_t axMg;
  int16_t ayMg;
  int16_t azMg;
  int16_t gxMilliRad;
  int16_t gyMilliRad;
  int16_t gzMilliRad;
};

ImuSample sampleRing[RING_BUFFER_CAPACITY];
uint16_t ringHead = 0;
uint16_t ringCount = 0;
uint32_t nextSeq = 0;
uint64_t lastSampleAtUs = 0;

bool deviceConnected = false;
bool notificationsEnabled = false;
bool syncLocked = false;
bool helloDirty = true;

uint32_t bootId = 0;
uint32_t currentSuperframeId = 0;
uint32_t nextSeqExpectedFromHub = 0;
uint8_t slotIndex = NODE_ID - 1;
uint8_t activeNodeCount = NODE_ID;
uint64_t lastSyncReceivedLocalUs = 0;
uint64_t flushDeadlineLocalUs = 0;
uint32_t lastFlushedSuperframeId = 0;
uint64_t lastHelloSentUs = 0;


static inline int16_t clampInt16(long value) {
  if (value < -32768L) return -32768;
  if (value > 32767L) return 32767;
  return static_cast<int16_t>(value);
}


static inline void writeU16LE(uint8_t* dest, uint16_t value) {
  dest[0] = static_cast<uint8_t>(value & 0xFF);
  dest[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
}


static inline void writeU32LE(uint8_t* dest, uint32_t value) {
  dest[0] = static_cast<uint8_t>(value & 0xFF);
  dest[1] = static_cast<uint8_t>((value >> 8) & 0xFF);
  dest[2] = static_cast<uint8_t>((value >> 16) & 0xFF);
  dest[3] = static_cast<uint8_t>((value >> 24) & 0xFF);
}


static inline void writeU64LE(uint8_t* dest, uint64_t value) {
  for (uint8_t i = 0; i < 8; ++i) {
    dest[i] = static_cast<uint8_t>((value >> (8 * i)) & 0xFF);
  }
}


static inline void writeI16LE(uint8_t* dest, int16_t value) {
  writeU16LE(dest, static_cast<uint16_t>(value));
}


static inline uint16_t readU16LE(const uint8_t* src) {
  return static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
}


static inline uint32_t readU32LE(const uint8_t* src) {
  return static_cast<uint32_t>(src[0]) |
         (static_cast<uint32_t>(src[1]) << 8) |
         (static_cast<uint32_t>(src[2]) << 16) |
         (static_cast<uint32_t>(src[3]) << 24);
}


static inline uint64_t readU64LE(const uint8_t* src) {
  uint64_t value = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    value |= static_cast<uint64_t>(src[i]) << (8 * i);
  }
  return value;
}


void writeHeader(uint8_t* buffer, uint8_t packetType, uint16_t payloadLen) {
  memcpy(buffer, PACKET_MAGIC, 4);
  buffer[4] = PROTOCOL_VERSION;
  buffer[5] = packetType;
  writeU16LE(buffer + 6, payloadLen);
}


size_t buildHelloPacket(uint8_t* buffer, size_t capacity) {
  const uint16_t payloadLen = 11;
  const size_t totalLen = 8 + payloadLen;
  if (capacity < totalLen) return 0;

  writeHeader(buffer, PACKET_TYPE_HELLO, payloadLen);
  buffer[8] = NODE_ID;
  writeU16LE(buffer + 9, syncLocked ? HELLO_FLAG_SYNC_LOCKED : 0);
  writeU32LE(buffer + 11, bootId);
  writeU32LE(buffer + 15, FIRMWARE_VERSION);
  return totalLen;
}


size_t buildDataPacket(
  uint8_t* buffer,
  size_t capacity,
  const ImuSample* samples,
  uint8_t sampleCount,
  uint16_t flags
) {
  if (sampleCount == 0) return 0;

  const uint16_t payloadLen = DATA_PREFIX_BYTES + (sampleCount * SAMPLE_BYTES);
  const size_t totalLen = 8 + payloadLen;
  if (capacity < totalLen) return 0;

  writeHeader(buffer, PACKET_TYPE_DATA, payloadLen);
  buffer[8] = NODE_ID;
  buffer[9] = sampleCount;
  writeU16LE(buffer + 10, flags);
  writeU32LE(buffer + 12, samples[0].seq);
  writeU64LE(buffer + 16, samples[0].tUs);

  size_t offset = 24;
  for (uint8_t i = 0; i < sampleCount; ++i) {
    writeI16LE(buffer + offset + 0, samples[i].axMg);
    writeI16LE(buffer + offset + 2, samples[i].ayMg);
    writeI16LE(buffer + offset + 4, samples[i].azMg);
    writeI16LE(buffer + offset + 6, samples[i].gxMilliRad);
    writeI16LE(buffer + offset + 8, samples[i].gyMilliRad);
    writeI16LE(buffer + offset + 10, samples[i].gzMilliRad);
    offset += SAMPLE_BYTES;
  }

  return totalLen;
}


void pushSample(const ImuSample& sample) {
  if (ringCount < RING_BUFFER_CAPACITY) {
    sampleRing[(ringHead + ringCount) % RING_BUFFER_CAPACITY] = sample;
    ringCount++;
    return;
  }

  sampleRing[ringHead] = sample;
  ringHead = (ringHead + 1) % RING_BUFFER_CAPACITY;
}


bool hasSamples() {
  return ringCount > 0;
}


uint32_t oldestSeq() {
  if (!hasSamples()) return nextSeq;
  return sampleRing[ringHead].seq;
}


uint32_t newestSeq() {
  if (!hasSamples()) return nextSeq;
  return sampleRing[(ringHead + ringCount - 1) % RING_BUFFER_CAPACITY].seq;
}


bool getSampleBySeq(uint32_t seq, ImuSample* out) {
  if (!hasSamples()) return false;
  const uint32_t firstSeq = oldestSeq();
  const uint32_t lastSeq = newestSeq();
  if (seq < firstSeq || seq > lastSeq) return false;

  const uint32_t offset = seq - firstSeq;
  const uint16_t index = static_cast<uint16_t>((ringHead + offset) % RING_BUFFER_CAPACITY);
  if (sampleRing[index].seq != seq) return false;

  *out = sampleRing[index];
  return true;
}


void sampleIfDue() {
  uint64_t nowUs = esp_timer_get_time();
  if (lastSampleAtUs == 0) {
    lastSampleAtUs = nowUs - SAMPLE_PERIOD_US;
  }

  while ((nowUs - lastSampleAtUs) >= SAMPLE_PERIOD_US) {
    lastSampleAtUs += SAMPLE_PERIOD_US;

    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    ImuSample sample;
    sample.seq = nextSeq++;
    sample.tUs = lastSampleAtUs;
    sample.axMg = clampInt16(lround((a.acceleration.x * 1000.0) / 9.80665));
    sample.ayMg = clampInt16(lround((a.acceleration.y * 1000.0) / 9.80665));
    sample.azMg = clampInt16(lround((a.acceleration.z * 1000.0) / 9.80665));
    sample.gxMilliRad = clampInt16(lround(g.gyro.x * 1000.0));
    sample.gyMilliRad = clampInt16(lround(g.gyro.y * 1000.0));
    sample.gzMilliRad = clampInt16(lround(g.gyro.z * 1000.0));

    pushSample(sample);
  }
}


void maybeSendHello() {
  if (!deviceConnected || !notificationsEnabled || streamCharacteristic == nullptr) return;

  const uint64_t nowUs = esp_timer_get_time();
  if (!helloDirty && (nowUs - lastHelloSentUs) < HELLO_INTERVAL_US) return;

  uint8_t packet[32];
  const size_t length = buildHelloPacket(packet, sizeof(packet));
  if (length == 0) return;

  streamCharacteristic->setValue(packet, length);
  streamCharacteristic->notify();

  lastHelloSentUs = nowUs;
  helloDirty = false;
}


void handleSyncTimeout() {
  if (!syncLocked || lastSyncReceivedLocalUs == 0) return;
  const uint64_t nowUs = esp_timer_get_time();
  if ((nowUs - lastSyncReceivedLocalUs) > SYNC_TIMEOUT_US) {
    syncLocked = false;
    helloDirty = true;
  }
}


void flushPendingDataIfDue() {
  if (!deviceConnected || !notificationsEnabled || !syncLocked || streamCharacteristic == nullptr) return;
  if (!hasSamples()) return;

  const uint64_t nowUs = esp_timer_get_time();
  if (nowUs < flushDeadlineLocalUs) return;
  if (currentSuperframeId == lastFlushedSuperframeId) return;

  uint32_t cursorSeq = nextSeqExpectedFromHub;
  const uint32_t firstSeq = oldestSeq();
  const uint32_t lastSeq = newestSeq();
  if (cursorSeq < firstSeq) cursorSeq = firstSeq;

  if (cursorSeq > lastSeq) {
    lastFlushedSuperframeId = currentSuperframeId;
    return;
  }

  uint8_t packetBuffer[256];
  ImuSample batch[16];
  uint8_t packetsSent = 0;

  while (cursorSeq <= lastSeq && packetsSent < MAX_PACKETS_PER_SLOT) {
    uint8_t count = 0;
    while (count < MAX_SAMPLES_PER_PACKET && cursorSeq <= lastSeq) {
      if (!getSampleBySeq(cursorSeq, &batch[count])) break;
      cursorSeq++;
      count++;
    }

    if (count == 0) break;

    const size_t length = buildDataPacket(packetBuffer, sizeof(packetBuffer), batch, count, 0);
    if (length == 0) break;

    streamCharacteristic->setValue(packetBuffer, length);
    streamCharacteristic->notify();
    packetsSent++;
  }

  lastFlushedSuperframeId = currentSuperframeId;
}


bool handleSyncPacket(const uint8_t* payload, size_t payloadLen) {
  if (payloadLen != 22) return false;

  currentSuperframeId = readU32LE(payload + 0);
  const uint64_t hubTimeUs = readU64LE(payload + 4);
  (void)hubTimeUs;
  nextSeqExpectedFromHub = readU32LE(payload + 12);

  const uint16_t samplePeriodUs = readU16LE(payload + 16);
  const uint16_t superframeMs = readU16LE(payload + 18);
  const uint8_t nextSlotIndex = payload[20];
  const uint8_t nextActiveNodeCount = payload[21];

  if (samplePeriodUs != SAMPLE_PERIOD_US) {
    Serial.println("Hub sample period mismatch, ignoring sync.");
    return false;
  }

  if (superframeMs != SUPERFRAME_MS) {
    Serial.println("Hub superframe mismatch, ignoring sync.");
    return false;
  }

  slotIndex = nextSlotIndex;
  activeNodeCount = nextActiveNodeCount;
  syncLocked = true;
  helloDirty = true;

  lastSyncReceivedLocalUs = esp_timer_get_time();
  flushDeadlineLocalUs =
    lastSyncReceivedLocalUs +
    (static_cast<uint64_t>(SYNC_LEAD_MS) * 1000ULL) +
    (static_cast<uint64_t>(slotIndex) * static_cast<uint64_t>(NODE_SLOT_MS) * 1000ULL);

  if (currentSuperframeId != lastFlushedSuperframeId) {
    // keep existing lastFlushedSuperframeId so we flush once for this superframe
  }

  return true;
}


void handleControlWrite(const uint8_t* raw, size_t length) {
  if (length < 8) return;
  if (memcmp(raw, PACKET_MAGIC, 4) != 0) return;
  if (raw[4] != PROTOCOL_VERSION) return;

  const uint8_t packetType = raw[5];
  const uint16_t payloadLen = readU16LE(raw + 6);
  if (length != static_cast<size_t>(8 + payloadLen)) return;
  if (packetType != PACKET_TYPE_SYNC) return;

  if (handleSyncPacket(raw + 8, payloadLen)) {
    Serial.print("SYNC superframe=");
    Serial.print(currentSuperframeId);
    Serial.print(" nextSeq=");
    Serial.print(nextSeqExpectedFromHub);
    Serial.print(" slot=");
    Serial.print(slotIndex);
    Serial.print("/");
    Serial.println(activeNodeCount);
  }
}


class HARServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* pServer) override {
    (void)pServer;
    deviceConnected = true;
    notificationsEnabled = false;
    syncLocked = false;
    helloDirty = true;
    Serial.println("BLE client connected.");
  }

  void onDisconnect(NimBLEServer* pServer) override {
    (void)pServer;
    deviceConnected = false;
    notificationsEnabled = false;
    syncLocked = false;
    helloDirty = true;
    NimBLEDevice::startAdvertising();
    Serial.println("BLE client disconnected.");
  }
};


class ControlCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pCharacteristic) override {
    std::string value = pCharacteristic->getValue();
    handleControlWrite(reinterpret_cast<const uint8_t*>(value.data()), value.size());
  }
};


class StreamCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic* pCharacteristic, ble_gap_conn_desc* desc, uint16_t subValue) override {
    (void)pCharacteristic;
    (void)desc;
    notificationsEnabled = (subValue & 0x01) != 0;
    helloDirty = true;
    Serial.print("Notifications ");
    Serial.println(notificationsEnabled ? "enabled" : "disabled");
  }
};


void setupBLE() {
  NimBLEDevice::init(DEVICE_NAME);
  NimBLEDevice::setMTU(PREFERRED_ATT_MTU);

  NimBLEServer* server = NimBLEDevice::createServer();
  server->setCallbacks(new HARServerCallbacks());

  NimBLEService* service = server->createService(HAR_SERVICE_UUID);

  controlCharacteristic = service->createCharacteristic(
    CONTROL_CHAR_UUID,
    NIMBLE_PROPERTY::WRITE
  );
  controlCharacteristic->setCallbacks(new ControlCallbacks());

  streamCharacteristic = service->createCharacteristic(
    STREAM_CHAR_UUID,
    NIMBLE_PROPERTY::NOTIFY
  );
  streamCharacteristic->setCallbacks(new StreamCallbacks());

  service->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(HAR_SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->start();
}


void setup() {
  Serial.begin(115200);
  delay(250);

  Wire.begin(SDA_PIN, SCL_PIN, 400000);

  if (!mpu.begin(0x68, &Wire)) {
    Serial.println("Failed to find MPU6050!");
    while (true) {
      delay(1000);
    }
  }

  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  bootId = esp_random();
  lastFlushedSuperframeId = 0xFFFFFFFFUL;

  setupBLE();

  Serial.print("BLE soft-TDMA node ready: ");
  Serial.println(DEVICE_NAME);
  Serial.print("Boot ID: ");
  Serial.println(bootId);
}


void loop() {
  sampleIfDue();
  handleSyncTimeout();
  maybeSendHello();
  flushPendingDataIfDue();
  delay(1);
}
