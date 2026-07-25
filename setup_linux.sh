#!/usr/bin/env bash
set -euo pipefail

echo "Install ADB if needed:"
echo "  sudo apt update && sudo apt install android-tools-adb -y"
echo

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

uv venv --python 3.11 .venv
uv pip install -e ".[dev]"

echo
echo "Done. Activate with:"
echo "  source .venv/bin/activate"
echo
echo "Then check devices:"
echo "  pogo devices"
