#!/usr/bin/env bash
set -euo pipefail

cd "${HOME}/Downloads"
wget -O platform-tools-latest-linux.zip https://dl.google.com/android/repository/platform-tools-latest-linux.zip
unzip -o platform-tools-latest-linux.zip
mkdir -p "${HOME}/android"
rm -rf "${HOME}/android/platform-tools"
mv platform-tools "${HOME}/android/platform-tools"

if ! grep -q 'android/platform-tools' "${HOME}/.bashrc"; then
  echo 'export PATH="$HOME/android/platform-tools:$PATH"' >> "${HOME}/.bashrc"
fi

export PATH="${HOME}/android/platform-tools:${PATH}"

echo "Using adb:"
which adb
adb version

echo
echo "Restart your terminal or run:"
echo 'source ~/.bashrc'
