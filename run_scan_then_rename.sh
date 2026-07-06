#!/usr/bin/env bash
set -euo pipefail

COUNT="${1:-5}"
ADB_SERIAL="${2:-}"

if [[ -n "$ADB_SERIAL" ]]; then
  pogo workflow --count "$COUNT" --adb-serial "$ADB_SERIAL"
else
  pogo workflow --count "$COUNT"
fi
