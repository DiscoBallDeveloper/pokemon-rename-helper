#!/usr/bin/env bash
set -euo pipefail

echo "This script resets stale ADB Wi-Fi sessions on the laptop."
echo "After this, toggle Wireless debugging OFF/ON on the phone and reconnect."

adb disconnect || true
adb kill-server || true
adb start-server
adb devices

cat <<'EOF'

Next steps on phone:
  Developer options -> Wireless debugging -> OFF -> ON

Then on laptop:
  adb connect PHONE_IP:CONNECT_PORT
  adb devices

Expected:
  PHONE_IP:CONNECT_PORT    device

Then:
  pogo workflow --count 5 --adb-serial PHONE_IP:CONNECT_PORT
EOF
