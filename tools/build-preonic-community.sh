#!/usr/bin/env bash
# Preonic-only rebuild from the exact master Kaleidoscope and installed official core.
# Preserve master BLE pairing, encryption, bonds and slot addressing unchanged.
set -euo pipefail
cd "$(dirname "$0")/.."

MASTER_KALEIDOSCOPE_SHA=b436a6089f388c12178ebd6519cbe4d3db365ccc

# make setup checks out the bundle's master-pinned submodule and official nRF52 BSP.
# Refuse to silently build against a community BLE fork or different revision.
actual_sha="$(git -C lib/Kaleidoscope rev-parse HEAD)"
if [ "$actual_sha" != "$MASTER_KALEIDOSCOPE_SHA" ]; then
  echo "Unexpected Kaleidoscope revision: $actual_sha (expected master $MASTER_KALEIDOSCOPE_SHA)" >&2
  exit 1
fi
echo "Verified master Kaleidoscope: $actual_sha"

# Only Preonic USB fallback and battery-monitoring behavior + keyclick.
# No patches to Bluefruit.cpp, bonding.cpp, BLESecurity.cpp or BLEConnection.cpp.
python3 tools/patch-preonic-runtime.py

preonic_sketch="lib/Kaleidoscope/plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
grep -Fq '  Keyclick.enable();' "$preonic_sketch"
if grep -Fq '  Keyclick.disable();' "$preonic_sketch"; then
  echo "Unexpected Keyclick.disable() remains" >&2
  exit 1
fi

# Assert master BLE and upstream nRF52 core have not been altered.
git -C lib/Kaleidoscope diff --exit-code -- src/kaleidoscope/driver/ble/Bluefruit.cpp src/kaleidoscope/driver/ble/Bluefruit.h
echo "Verified: master BLE pairing and bonding source unchanged"

make Keyboardio/Preonic
test -s output/Keyboardio/Preonic/default.zip
echo "Preonic firmware: output/Keyboardio/Preonic/default.zip"
