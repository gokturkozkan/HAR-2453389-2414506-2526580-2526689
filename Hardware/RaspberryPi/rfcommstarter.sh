set -euo pipefail

MACS=(
  "08:A6:F7:47:4C:CE"
  "08:D1:F9:DF:D7:BA"
  "94:54:C5:E8:ED:D2"
  "C8:2E:18:8E:EA:DE"
  
)

CHANNEL=1
START_INDEX=0

sudo rfcomm release all || true

i=$START_INDEX
for mac in "${MACS[@]}"; do
  echo "Binding rfcomm${i} -> ${mac} ch${CHANNEL}"
  sudo rfcomm bind "$i" "$mac" "$CHANNEL"
  i=$((i+1))
done

echo "Done."
sudo rfcomm
