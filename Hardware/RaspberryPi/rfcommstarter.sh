set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_PATH="${HAR_BLE_NODE_REGISTRY:-${SCRIPT_DIR}/ble_node_registry.json}"
CHANNEL="${RFCOMM_CHANNEL:-1}"

if [[ ! -f "${REGISTRY_PATH}" ]]; then
  echo "Registry not found: ${REGISTRY_PATH}" >&2
  exit 1
fi

sudo rfcomm release all || true

mapfile -t NODE_ROWS < <(
  python3 - "${REGISTRY_PATH}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)

for item in sorted(data.get("nodes", []), key=lambda row: int(row["id"])):
    node_id = int(item["id"])
    index = node_id - 1
    name = str(item.get("name", f"ESP32_NODE_{node_id}"))
    mac = str(item["mac"])
    print(f"{index}|{mac}|{name}")
PY
)

for row in "${NODE_ROWS[@]}"; do
  IFS="|" read -r index mac name <<<"${row}"
  echo "Binding rfcomm${index} -> ${name} (${mac}) ch${CHANNEL}"
  sudo rfcomm bind "${index}" "${mac}" "${CHANNEL}"
done

echo "Done."
sudo rfcomm
