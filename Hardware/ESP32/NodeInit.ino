#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_timer.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "NodeConfig.h"

const int SDA_PIN = 21;
const int SCL_PIN = 22;

const uint8_t PROTOCOL_VERSION = 1;
const char MAGIC[4] = {'H', 'A', 'R', 'W'};
const uint8_t PACKET_TYPE_HELLO = 1;
const uint8_t PACKET_TYPE_SYNC = 2;
const uint8_t PACKET_TYPE_DATA = 3;
const uint16_t HELLO_FLAG_SYNC_LOCKED = 1 << 0;

const uint8_t MAX_NODE_ID = 7;
const size_t SAMPLE_BUFFER_CAPACITY = 256;
const uint8_t MAX_BATCH_SAMPLES = 16;
const uint32_t SAMPLE_PERIOD_US = 40000;
const uint32_t SUPERFRAME_US = 300000;
const uint32_t SYNC_LEAD_US = 20000;
const uint32_t SLOT_US = 40000;
const uint32_t SYNC_TIMEOUT_US = 900000;
const uint32_t HELLO_INTERVAL_MS = 500;

Adafruit_MPU6050 mpu;
WiFiUDP syncUdp;
WiFiUDP dataUdp;

#pragma pack(push, 1)
struct PacketHeader {
  char magic[4];
  uint8_t version;
  uint8_t type;
  uint16_t payloadSize;
};

struct HelloPayload {
  uint8_t nodeId;
  uint8_t reserved;
  uint16_t flags;
  uint32_t bootId;
  uint32_t firmwareVersion;
};

struct SyncPayload {
  uint32_t superframeId;
  uint64_t hubTimeUs;
  uint32_t nextSeqExpected[MAX_NODE_ID];
};

struct DataPrefix {
  uint8_t nodeId;
  uint8_t sampleCount;
  uint16_t reserved;
  uint32_t firstSeq;
  uint64_t firstSampleTimeUs;
};

struct PackedSample {
  int16_t axMg;
  int16_t ayMg;
  int16_t azMg;
  int16_t gxMilliRad;
  int16_t gyMilliRad;
  int16_t gzMilliRad;
};
#pragma pack(pop)

struct SampleFrame {
  uint32_t seq;
  uint64_t localTimeUs;
  PackedSample sample;
};

SampleFrame sampleBuffer[SAMPLE_BUFFER_CAPACITY];
size_t bufferStart = 0;
size_t bufferCount = 0;
uint32_t nextSampleSeq = 0;
uint32_t bootId = 0;

bool hubOffsetValid = false;
bool syncLocked = false;
bool syncHelloPending = false;
uint64_t lastSyncLocalUs = 0;
int64_t hubOffsetUs = 0;
uint32_t scheduledSuperframeId = 0;
uint64_t scheduledSlotLocalUs = 0;
bool slotScheduled = false;
uint32_t lastSentSuperframeId = 0;

uint64_t nextSampleDueUs = 0;
unsigned long lastWifiRetryMs = 0;
unsigned long lastHelloMs = 0;
unsigned long lastHubResolveMs = 0;
IPAddress resolvedHubIp = HUB_IP;
bool hubIpResolved = false;

int16_t clampToInt16(long value) {
  if (value > 32767L) {
    return 32767;
  }
  if (value < -32768L) {
    return -32768;
  }
  return static_cast<int16_t>(value);
}

uint64_t localNowUs() {
  return static_cast<uint64_t>(esp_timer_get_time());
}

int64_t estimateHubTimeUs(uint64_t localTimeUs) {
  if (!hubOffsetValid) {
    return static_cast<int64_t>(localTimeUs);
  }
  return static_cast<int64_t>(localTimeUs) + hubOffsetUs;
}

uint64_t hubToLocalUs(uint64_t hubTimeUs) {
  if (!hubOffsetValid) {
    return localNowUs();
  }
  return static_cast<uint64_t>(static_cast<int64_t>(hubTimeUs) - hubOffsetUs);
}

void pushSample(const SampleFrame& frame) {
  if (bufferCount == SAMPLE_BUFFER_CAPACITY) {
    bufferStart = (bufferStart + 1) % SAMPLE_BUFFER_CAPACITY;
    bufferCount--;
  }
  const size_t index = (bufferStart + bufferCount) % SAMPLE_BUFFER_CAPACITY;
  sampleBuffer[index] = frame;
  bufferCount++;
}

void dropAckedSamples(uint32_t nextSeqExpected) {
  while (bufferCount > 0) {
    const SampleFrame& current = sampleBuffer[bufferStart];
    if (current.seq >= nextSeqExpected) {
      break;
    }
    bufferStart = (bufferStart + 1) % SAMPLE_BUFFER_CAPACITY;
    bufferCount--;
  }
}

void ensureWifiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  unsigned long nowMs = millis();
  if ((nowMs - lastWifiRetryMs) < WIFI_RETRY_INTERVAL_MS) {
    return;
  }

  lastWifiRetryMs = nowMs;
  syncLocked = false;
  slotScheduled = false;
  syncHelloPending = false;

  Serial.printf("Connecting to Wi-Fi SSID '%s'...\n", WIFI_SSID);
  WiFi.disconnect(true, true);
  WiFi.setHostname(DEVICE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void resolveHubAddress(bool force = false) {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  const unsigned long nowMs = millis();
  if (!force && ((nowMs - lastHubResolveMs) < HUB_RESOLVE_RETRY_MS)) {
    return;
  }
  lastHubResolveMs = nowMs;

  IPAddress discovered;
  if (WiFi.hostByName(HUB_HOSTNAME, discovered)) {
    resolvedHubIp = discovered;
    hubIpResolved = true;
    Serial.printf(
      "[NET] Hub hostname '%s' resolved to %s\n",
      HUB_HOSTNAME,
      resolvedHubIp.toString().c_str()
    );
    return;
  }

  resolvedHubIp = HUB_IP;
  hubIpResolved = false;
  Serial.printf(
    "[NET] Could not resolve '%s', using fallback %s\n",
    HUB_HOSTNAME,
    resolvedHubIp.toString().c_str()
  );
}

void sendHello(bool withSyncLock) {
  uint8_t packet[sizeof(PacketHeader) + sizeof(HelloPayload)];
  PacketHeader header;
  memcpy(header.magic, MAGIC, sizeof(MAGIC));
  header.version = PROTOCOL_VERSION;
  header.type = PACKET_TYPE_HELLO;
  header.payloadSize = sizeof(HelloPayload);

  HelloPayload payload;
  payload.nodeId = NODE_ID;
  payload.reserved = 0;
  payload.flags = withSyncLock ? HELLO_FLAG_SYNC_LOCKED : 0;
  payload.bootId = bootId;
  payload.firmwareVersion = FIRMWARE_VERSION;

  memcpy(packet, &header, sizeof(header));
  memcpy(packet + sizeof(header), &payload, sizeof(payload));

  dataUdp.beginPacket(resolvedHubIp, HUB_DATA_PORT);
  dataUdp.write(packet, sizeof(packet));
  dataUdp.endPacket();

  Serial.printf(
    "[HELLO] node=%u sync_locked=%s ip=%s\n",
    NODE_ID,
    withSyncLock ? "yes" : "no",
    WiFi.localIP().toString().c_str()
  );
}

void maybeSendHello() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  resolveHubAddress();

  const unsigned long nowMs = millis();
  if ((nowMs - lastHelloMs) < HELLO_INTERVAL_MS) {
    return;
  }

  if (!syncLocked) {
    sendHello(false);
    lastHelloMs = nowMs;
    return;
  }

  if (syncHelloPending) {
    sendHello(true);
    syncHelloPending = false;
    lastHelloMs = nowMs;
  }
}

void captureSample(uint64_t scheduledTimeUs) {
  sensors_event_t acceleration;
  sensors_event_t gyro;
  sensors_event_t temperature;
  mpu.getEvent(&acceleration, &gyro, &temperature);

  SampleFrame frame;
  frame.seq = nextSampleSeq++;
  frame.localTimeUs = scheduledTimeUs;
  frame.sample.axMg = clampToInt16(lround(acceleration.acceleration.x * (1000.0f / 9.80665f)));
  frame.sample.ayMg = clampToInt16(lround(acceleration.acceleration.y * (1000.0f / 9.80665f)));
  frame.sample.azMg = clampToInt16(lround(acceleration.acceleration.z * (1000.0f / 9.80665f)));
  frame.sample.gxMilliRad = clampToInt16(lround(gyro.gyro.x * 1000.0f));
  frame.sample.gyMilliRad = clampToInt16(lround(gyro.gyro.y * 1000.0f));
  frame.sample.gzMilliRad = clampToInt16(lround(gyro.gyro.z * 1000.0f));
  pushSample(frame);
}

void maybeCaptureSamples() {
  const uint64_t nowUs = localNowUs();
  while (nowUs >= nextSampleDueUs) {
    captureSample(nextSampleDueUs);
    nextSampleDueUs += SAMPLE_PERIOD_US;
  }
}

void handleSyncPayload(const SyncPayload& payload) {
  const uint64_t receivedLocalUs = localNowUs();
  const int64_t observedOffset = static_cast<int64_t>(payload.hubTimeUs) - static_cast<int64_t>(receivedLocalUs);
  if (!hubOffsetValid) {
    hubOffsetUs = observedOffset;
  } else {
    hubOffsetUs = ((hubOffsetUs * 7) + observedOffset) / 8;
  }
  hubOffsetValid = true;
  lastSyncLocalUs = receivedLocalUs;

  const bool wasSyncLocked = syncLocked;
  syncLocked = true;
  if (!wasSyncLocked) {
    syncHelloPending = true;
  }

  dropAckedSamples(payload.nextSeqExpected[NODE_ID - 1]);

  const uint64_t superframeStartHubUs = static_cast<uint64_t>(payload.superframeId) * SUPERFRAME_US;
  const uint64_t slotStartHubUs = superframeStartHubUs + SYNC_LEAD_US + (static_cast<uint64_t>(NODE_ID - 1) * SLOT_US);
  scheduledSlotLocalUs = hubToLocalUs(slotStartHubUs);
  scheduledSuperframeId = payload.superframeId;
  slotScheduled = true;

  Serial.printf(
    "[SYNC] frame=%lu ack=%lu buffer=%u\n",
    static_cast<unsigned long>(payload.superframeId),
    static_cast<unsigned long>(payload.nextSeqExpected[NODE_ID - 1]),
    static_cast<unsigned int>(bufferCount)
  );
}

void processIncomingSync() {
  int packetSize = syncUdp.parsePacket();
  while (packetSize > 0) {
    const size_t maxBytes = sizeof(PacketHeader) + sizeof(SyncPayload);
    uint8_t packet[maxBytes];
    const int readLen = syncUdp.read(packet, sizeof(packet));
    if (readLen >= static_cast<int>(sizeof(PacketHeader) + sizeof(SyncPayload))) {
      PacketHeader header;
      memcpy(&header, packet, sizeof(header));
      if (
        memcmp(header.magic, MAGIC, sizeof(MAGIC)) == 0 &&
        header.version == PROTOCOL_VERSION &&
        header.type == PACKET_TYPE_SYNC &&
        header.payloadSize == sizeof(SyncPayload)
      ) {
        SyncPayload payload;
        memcpy(&payload, packet + sizeof(PacketHeader), sizeof(payload));
        handleSyncPayload(payload);
      }
    }
    packetSize = syncUdp.parsePacket();
  }
}

void maybeSendDataBatch() {
  if (WiFi.status() != WL_CONNECTED || !hubOffsetValid || !syncLocked || !slotScheduled) {
    return;
  }

  const uint64_t nowUs = localNowUs();
  if ((nowUs - lastSyncLocalUs) > SYNC_TIMEOUT_US) {
    syncLocked = false;
    slotScheduled = false;
    syncHelloPending = false;
    Serial.println("[SYNC] Lost sync lock");
    return;
  }

  if (scheduledSuperframeId == lastSentSuperframeId) {
    return;
  }

  const uint64_t slotEndLocalUs = scheduledSlotLocalUs + SLOT_US;
  if (nowUs < scheduledSlotLocalUs || nowUs > slotEndLocalUs) {
    return;
  }

  if (bufferCount == 0) {
    return;
  }

  const uint8_t batchCount = static_cast<uint8_t>(min(bufferCount, static_cast<size_t>(MAX_BATCH_SAMPLES)));
  const size_t packetSize = sizeof(PacketHeader) + sizeof(DataPrefix) + (batchCount * sizeof(PackedSample));
  uint8_t packet[sizeof(PacketHeader) + sizeof(DataPrefix) + (MAX_BATCH_SAMPLES * sizeof(PackedSample))];

  PacketHeader header;
  memcpy(header.magic, MAGIC, sizeof(MAGIC));
  header.version = PROTOCOL_VERSION;
  header.type = PACKET_TYPE_DATA;
  header.payloadSize = sizeof(DataPrefix) + (batchCount * sizeof(PackedSample));

  const SampleFrame& first = sampleBuffer[bufferStart];
  DataPrefix prefix;
  prefix.nodeId = NODE_ID;
  prefix.sampleCount = batchCount;
  prefix.reserved = 0;
  prefix.firstSeq = first.seq;
  const int64_t estimatedHubTimeUs = estimateHubTimeUs(first.localTimeUs);
  prefix.firstSampleTimeUs = estimatedHubTimeUs > 0 ? static_cast<uint64_t>(estimatedHubTimeUs) : 0;

  memcpy(packet, &header, sizeof(header));
  memcpy(packet + sizeof(header), &prefix, sizeof(prefix));

  size_t writeOffset = sizeof(header) + sizeof(prefix);
  for (uint8_t index = 0; index < batchCount; ++index) {
    const size_t sampleIndex = (bufferStart + index) % SAMPLE_BUFFER_CAPACITY;
    memcpy(packet + writeOffset, &sampleBuffer[sampleIndex].sample, sizeof(PackedSample));
    writeOffset += sizeof(PackedSample);
  }

  dataUdp.beginPacket(resolvedHubIp, HUB_DATA_PORT);
  dataUdp.write(packet, packetSize);
  dataUdp.endPacket();

  lastSentSuperframeId = scheduledSuperframeId;

  Serial.printf(
    "[DATA] frame=%lu first_seq=%lu count=%u buffered=%u\n",
    static_cast<unsigned long>(scheduledSuperframeId),
    static_cast<unsigned long>(prefix.firstSeq),
    static_cast<unsigned int>(batchCount),
    static_cast<unsigned int>(bufferCount)
  );
}

void setup() {
  Serial.begin(115200);
  delay(500);

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

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setHostname(DEVICE_HOSTNAME);
  syncUdp.begin(HUB_SYNC_PORT);

  bootId = esp_random();
  nextSampleDueUs = localNowUs();
  lastSentSuperframeId = 0xFFFFFFFFu;

  Serial.println("MPU6050 ready.");
  Serial.printf("Node %u firmware %lu boot %lu\n", NODE_ID, static_cast<unsigned long>(FIRMWARE_VERSION), static_cast<unsigned long>(bootId));

  ensureWifiConnected();
}

void loop() {
  ensureWifiConnected();
  resolveHubAddress();
  maybeCaptureSamples();
  processIncomingSync();
  maybeSendHello();
  maybeSendDataBatch();
  delay(1);
}
