#pragma once

#include <Arduino.h>
#include <WiFi.h>

#if __has_include("NodeConfig.local.h")
#include "NodeConfig.local.h"
#endif

#ifndef HAR_NODE_ID
#define HAR_NODE_ID 4
#endif
#ifndef HAR_FIRMWARE_VERSION
#define HAR_FIRMWARE_VERSION 1
#endif
#ifndef HAR_WIFI_SSID
#define HAR_WIFI_SSID "REPLACE_WITH_WIFI_SSID"
#endif
#ifndef HAR_WIFI_PASSWORD
#define HAR_WIFI_PASSWORD "REPLACE_WITH_WIFI_PASSWORD"
#endif
#ifndef HAR_WIFI_COUNTRY
#define HAR_WIFI_COUNTRY "CY"
#endif
#ifndef HAR_DEVICE_HOSTNAME
#define HAR_DEVICE_HOSTNAME "har-node-4"
#endif
#ifndef HAR_HUB_HOSTNAME
#define HAR_HUB_HOSTNAME "har-hub.local"
#endif
#ifndef HAR_HUB_IP_1
#define HAR_HUB_IP_1 192
#endif
#ifndef HAR_HUB_IP_2
#define HAR_HUB_IP_2 168
#endif
#ifndef HAR_HUB_IP_3
#define HAR_HUB_IP_3 1
#endif
#ifndef HAR_HUB_IP_4
#define HAR_HUB_IP_4 50
#endif
#ifndef HAR_HUB_SYNC_PORT
#define HAR_HUB_SYNC_PORT 39000
#endif
#ifndef HAR_HUB_DATA_PORT
#define HAR_HUB_DATA_PORT 39001
#endif
#ifndef HAR_WIFI_RETRY_INTERVAL_MS
#define HAR_WIFI_RETRY_INTERVAL_MS 5000
#endif
#ifndef HAR_HUB_RESOLVE_RETRY_MS
#define HAR_HUB_RESOLVE_RETRY_MS 5000
#endif

static constexpr uint8_t NODE_ID = HAR_NODE_ID;
static constexpr uint32_t FIRMWARE_VERSION = HAR_FIRMWARE_VERSION;

static constexpr char WIFI_SSID[] = HAR_WIFI_SSID;
static constexpr char WIFI_PASSWORD[] = HAR_WIFI_PASSWORD;
static constexpr char WIFI_COUNTRY[] = HAR_WIFI_COUNTRY;

static constexpr char DEVICE_HOSTNAME[] = HAR_DEVICE_HOSTNAME;
static constexpr char HUB_HOSTNAME[] = HAR_HUB_HOSTNAME;
static const IPAddress HUB_IP(HAR_HUB_IP_1, HAR_HUB_IP_2, HAR_HUB_IP_3, HAR_HUB_IP_4);
static constexpr uint16_t HUB_SYNC_PORT = HAR_HUB_SYNC_PORT;
static constexpr uint16_t HUB_DATA_PORT = HAR_HUB_DATA_PORT;

static constexpr uint32_t WIFI_RETRY_INTERVAL_MS = HAR_WIFI_RETRY_INTERVAL_MS;
static constexpr uint32_t HUB_RESOLVE_RETRY_MS = HAR_HUB_RESOLVE_RETRY_MS;
