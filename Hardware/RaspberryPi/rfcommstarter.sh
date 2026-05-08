set -euo pipefail

MACS=(
  "08:A6:F7:47:4C:CE"
  "94:54:C5:E7:E4:1A"
  "94:54:C5:E7:E7:16"
  "C8:2E:18:8E:EA:DE"
  "10:06:1C:85:EC:86"
  "08:D1:F9:DF:D7:BA"
  "94:54:C5:E8:ED:D2"
  
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
