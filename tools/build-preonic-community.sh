#!/usr/bin/env bash
# Preonic-only integration of the community BLE and battery fixes.
set -euo pipefail

cd "$(dirname "$0")/.."

KALEIDOSCOPE_SHA=e68f021d4dda8c090cfd2db370f12f25304135aa
NRF52_SHA=d4503ef36bcbc85cae9331862d4573626c249947

# The regular bundle setup installs the toolchains and official core first.
test -d lib/Kaleidoscope/.git || test -f lib/Kaleidoscope/.git
git -C lib/Kaleidoscope fetch --depth=1 \
  https://github.com/ianfajardo/Kaleidoscope.git "$KALEIDOSCOPE_SHA"
git -C lib/Kaleidoscope checkout --detach "$KALEIDOSCOPE_SHA"
test "$(git -C lib/Kaleidoscope rev-parse HEAD)" = "$KALEIDOSCOPE_SHA"

temp_core="$(mktemp -d)"
trap 'rm -rf "$temp_core"' EXIT
git -C "$temp_core" init -q
git -C "$temp_core" fetch --depth=1 \
  https://github.com/ianfajardo/Keyboardio_nRF52_Arduino.git "$NRF52_SHA"
git -C "$temp_core" checkout --detach FETCH_HEAD
test "$(git -C "$temp_core" rev-parse HEAD)" = "$NRF52_SHA"

# Patch only Bluefruit, not the other boards or their sketches.
core_root="${ARDUINO_DIRECTORIES_DATA:-$PWD/.arduino/data}/packages/keyboardio/hardware/nrf52"
mapfile -t candidates < <(find "$core_root" -mindepth 1 -maxdepth 1 -type d \
  -exec test -d '{}/libraries/Bluefruit52Lib' \; -print)
if [ "${#candidates[@]}" -ne 1 ]; then
  echo "Expected exactly one installed Keyboardio nRF52 core; found ${#candidates[@]}" >&2
  exit 1
fi
test -d "$temp_core/libraries/Bluefruit52Lib"
cp -a "$temp_core/libraries/Bluefruit52Lib/." \
  "${candidates[0]}/libraries/Bluefruit52Lib/"

# Apply the checked Preonic-only runtime fixes on top of the pinned community code.
python3 tools/patch-preonic-runtime.py
# Confirm the build will use the requested ON-at-boot keyclick setting.
preonic_sketch="lib/Kaleidoscope/plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
grep -Fq '  Keyclick.enable();' "$preonic_sketch"
if grep -Fq '  Keyclick.disable();' "$preonic_sketch"; then
  echo "Unexpected Keyclick.disable() remains in Preonic sketch" >&2
  exit 1
fi
echo "Verified: Preonic Keyclick enabled by default"

# Existing Bundle Makefile generates output/Keyboardio/Preonic/default.zip.
make Keyboardio/Preonic
test -s output/Keyboardio/Preonic/default.zip
echo "Preonic firmware: output/Keyboardio/Preonic/default.zip"
