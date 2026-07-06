#!/usr/bin/env bash
set -euo pipefail

echo "Install ADB if needed:"
echo "  sudo apt update && sudo apt install android-tools-adb -y"
echo

if conda env list | grep -q '^pogo-automation '; then
  conda env update -f environment.yml --prune
else
  conda env create -f environment.yml
fi

echo
echo "Done. Activate with:"
echo "  conda activate pogo-automation"
echo
echo "Then check devices:"
echo "  pogo devices"
