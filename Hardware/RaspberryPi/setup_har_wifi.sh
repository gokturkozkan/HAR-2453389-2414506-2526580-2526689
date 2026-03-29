#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SSID=""
PASSWORD=""
COUNTRY="CY"
HOSTNAME_VALUE="har-hub"
BACKEND_PORT="3000"
SYNC_PORT="39000"
DATA_PORT="39001"
UNITY_TCP_PORT="5005"
UNITY_DISCOVERY_PORT="5006"
HUB_IP=""
SKIP_WIFI=0

usage() {
  cat <<EOF
Usage:
  sudo ./Hardware/RaspberryPi/setup_har_wifi.sh --ssid "<wifi>" --password "<password>" [options]

Options:
  --ssid <name>               Wi-Fi SSID for the Raspberry Pi and ESP32 nodes
  --password <pass>           Wi-Fi password
  --country <code>            Wi-Fi country code (default: ${COUNTRY})
  --hostname <name>           Raspberry Pi hostname without .local (default: ${HOSTNAME_VALUE})
  --hub-ip <ip>               Fallback hub IP to write into ESP config
  --backend-port <port>       Backend HTTP port (default: ${BACKEND_PORT})
  --sync-port <port>          ESP sync UDP port (default: ${SYNC_PORT})
  --data-port <port>          ESP data UDP port (default: ${DATA_PORT})
  --unity-tcp-port <port>     Unity bridge TCP port (default: ${UNITY_TCP_PORT})
  --unity-discovery-port <p>  Unity discovery UDP port (default: ${UNITY_DISCOVERY_PORT})
  --skip-wifi                 Skip changing Pi Wi-Fi; only write repo config + hostname/mdns
  --help                      Show this help

What this script does:
  1. Sets the Raspberry Pi hostname so other devices can reach it as <hostname>.local
  2. Enables mDNS via avahi-daemon
  3. Connects the Pi to the given Wi-Fi if possible
  4. Writes common project config files:
     - HAR-app/.env.local
     - Hardware/ESP32/NodeConfig.local.h
     - Hardware/RaspberryPi/har_network.env
EOF
}

log() {
  printf '\n[%s] %s\n' "HAR-WIFI" "$*"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must run as root. Try: sudo $0 $*"
    exit 1
  fi
}

set_hostname() {
  log "Setting hostname to ${HOSTNAME_VALUE}"
  if command -v hostnamectl >/dev/null 2>&1; then
    hostnamectl set-hostname "${HOSTNAME_VALUE}"
  else
    printf '%s\n' "${HOSTNAME_VALUE}" >/etc/hostname
    hostname "${HOSTNAME_VALUE}"
  fi

  if grep -qE '^127\.0\.1\.1[[:space:]]' /etc/hosts; then
    sed -i -E "s/^127\\.0\\.1\\.1[[:space:]].*/127.0.1.1\t${HOSTNAME_VALUE}/" /etc/hosts
  else
    printf '127.0.1.1\t%s\n' "${HOSTNAME_VALUE}" >>/etc/hosts
  fi
}

ensure_avahi() {
  log "Ensuring avahi-daemon is installed and enabled for ${HOSTNAME_VALUE}.local"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y avahi-daemon
  fi
  systemctl enable --now avahi-daemon
}

connect_wifi_nmcli() {
  log "Connecting to Wi-Fi using NetworkManager"
  nmcli radio wifi on || true
  nmcli dev wifi connect "${SSID}" password "${PASSWORD}" ifname wlan0
}

connect_wifi_wpa() {
  log "Connecting to Wi-Fi using wpa_supplicant"
  local conf="/etc/wpa_supplicant/wpa_supplicant.conf"
  if [[ ! -f "${conf}" ]]; then
    echo "wpa_supplicant config not found at ${conf}"
    exit 1
  fi

  cp "${conf}" "${conf}.bak.$(date +%s)"
  if ! grep -q "ssid=\"${SSID}\"" "${conf}"; then
    {
      printf '\ncountry=%s\n' "${COUNTRY}"
      wpa_passphrase "${SSID}" "${PASSWORD}"
    } >>"${conf}"
  fi

  if command -v wpa_cli >/dev/null 2>&1; then
    wpa_cli -i wlan0 reconfigure || true
  fi
  systemctl restart wpa_supplicant || true
  systemctl restart dhcpcd || true
}

connect_wifi() {
  if [[ "${SKIP_WIFI}" -eq 1 ]]; then
    log "Skipping Pi Wi-Fi configuration by request"
    return
  fi

  if [[ -z "${SSID}" || -z "${PASSWORD}" ]]; then
    echo "Wi-Fi SSID and password are required unless --skip-wifi is used."
    exit 1
  fi

  if command -v nmcli >/dev/null 2>&1; then
    connect_wifi_nmcli
    return
  fi

  if command -v wpa_passphrase >/dev/null 2>&1; then
    connect_wifi_wpa
    return
  fi

  echo "Could not find nmcli or wpa_passphrase on this Raspberry Pi."
  exit 1
}

detect_hub_ip() {
  if [[ -n "${HUB_IP}" ]]; then
    return
  fi

  sleep 2
  HUB_IP="$(hostname -I | awk '{print $1}')"
  if [[ -z "${HUB_IP}" ]]; then
    HUB_IP="192.168.1.50"
  fi
}

split_ip() {
  local ip="$1"
  IFS='.' read -r HUB_IP_1 HUB_IP_2 HUB_IP_3 HUB_IP_4 <<<"${ip}"
  if [[ -z "${HUB_IP_1:-}" || -z "${HUB_IP_2:-}" || -z "${HUB_IP_3:-}" || -z "${HUB_IP_4:-}" ]]; then
    echo "Invalid hub IP: ${ip}"
    exit 1
  fi
}

write_har_network_env() {
  log "Writing Hardware/RaspberryPi/har_network.env"
  cat >"${SCRIPT_DIR}/har_network.env" <<EOF
export HAR_HUB_HOSTNAME="${HOSTNAME_VALUE}.local"
export HAR_HUB_IP="${HUB_IP}"
export HAR_BACKEND_PORT="${BACKEND_PORT}"
export HAR_WIFI_SYNC_PORT="${SYNC_PORT}"
export HAR_WIFI_DATA_PORT="${DATA_PORT}"
export UNITY_BRIDGE_TCP_PORT="${UNITY_TCP_PORT}"
export UNITY_BRIDGE_DISCOVERY_PORT="${UNITY_DISCOVERY_PORT}"
EOF
}

write_mobile_env() {
  log "Writing HAR-app/.env.local"
  cat >"${REPO_DIR}/HAR-app/.env.local" <<EOF
EXPO_PUBLIC_HAR_BACKEND_PROTOCOL=http
EXPO_PUBLIC_HAR_HUB_HOST=${HOSTNAME_VALUE}.local
EXPO_PUBLIC_HAR_BACKEND_PORT=${BACKEND_PORT}
EOF
}

write_esp_local_header() {
  if [[ -z "${SSID}" || -z "${PASSWORD}" ]]; then
    log "Skipping Hardware/ESP32/NodeConfig.local.h because Wi-Fi SSID/password were not provided"
    return
  fi

  split_ip "${HUB_IP}"
  log "Writing Hardware/ESP32/NodeConfig.local.h"
  cat >"${REPO_DIR}/Hardware/ESP32/NodeConfig.local.h" <<EOF
#pragma once

#define HAR_WIFI_SSID "${SSID}"
#define HAR_WIFI_PASSWORD "${PASSWORD}"
#define HAR_WIFI_COUNTRY "${COUNTRY}"
#define HAR_HUB_HOSTNAME "${HOSTNAME_VALUE}.local"
#define HAR_HUB_IP_1 ${HUB_IP_1}
#define HAR_HUB_IP_2 ${HUB_IP_2}
#define HAR_HUB_IP_3 ${HUB_IP_3}
#define HAR_HUB_IP_4 ${HUB_IP_4}
#define HAR_HUB_SYNC_PORT ${SYNC_PORT}
#define HAR_HUB_DATA_PORT ${DATA_PORT}
EOF
}

print_summary() {
  cat <<EOF

Setup complete.

Shared network:
  Wi-Fi SSID: ${SSID:-<unchanged>}
  Pi hostname: ${HOSTNAME_VALUE}.local
  Hub IP fallback: ${HUB_IP}

Generated files:
  ${SCRIPT_DIR}/har_network.env
  ${REPO_DIR}/HAR-app/.env.local
  ${REPO_DIR}/Hardware/ESP32/NodeConfig.local.h (only if SSID/password were provided)

What you still need to do:
  1. Rebuild/restart the mobile app so it picks up HAR-app/.env.local
  2. Flash each ESP32 with its own NODE_ID and DEVICE_HOSTNAME in Hardware/ESP32/NodeConfig.h
  3. Run the backend and tdma_formatted.py on the Pi while it is on the same Wi-Fi
  4. Keep Unity on the same Wi-Fi; it will use discovery first and hostname fallback second

Ports still exist internally, but they are now centralized so you should not need to retype them across the project.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssid)
      SSID="$2"
      shift 2
      ;;
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --country)
      COUNTRY="$2"
      shift 2
      ;;
    --hostname)
      HOSTNAME_VALUE="$2"
      shift 2
      ;;
    --hub-ip)
      HUB_IP="$2"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    --sync-port)
      SYNC_PORT="$2"
      shift 2
      ;;
    --data-port)
      DATA_PORT="$2"
      shift 2
      ;;
    --unity-tcp-port)
      UNITY_TCP_PORT="$2"
      shift 2
      ;;
    --unity-discovery-port)
      UNITY_DISCOVERY_PORT="$2"
      shift 2
      ;;
    --skip-wifi)
      SKIP_WIFI=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

require_root "$@"
set_hostname
ensure_avahi
connect_wifi
detect_hub_ip
write_har_network_env
write_mobile_env
write_esp_local_header
print_summary
