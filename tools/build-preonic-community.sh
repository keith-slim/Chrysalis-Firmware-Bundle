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

# Passive diagnostics are compiled only into this Preonic artifact. They never
# change BLE/security decisions and preserve master BLE behavior.
core_root="${ARDUINO_DIRECTORIES_DATA:-$PWD/.arduino/data}/packages/keyboardio/hardware/nrf52"
mapfile -t cores < <(find "$core_root" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/libraries/Bluefruit52Lib/src/BLESecurity.cpp' \; -print)
test "${#cores[@]}" -eq 1
python3 tools/patch-preonic-bonding.py "${cores[0]}"
python3 tools/patch-preonic-runtime.py

preonic_sketch="lib/Kaleidoscope/plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
grep -Fq '  Keyclick.enable();' "$preonic_sketch"
if grep -Fq '  Keyclick.disable();' "$preonic_sketch"; then
  echo "Unexpected Keyclick.disable() remains" >&2
  exit 1
fi

# Assert master BLE and upstream nRF52 core have not been altered.
# BLE source has instrumentation only; master is still the source of truth.
if git -C lib/Kaleidoscope diff -- src/kaleidoscope/driver/ble/Bluefruit.cpp | grep -E '^[+-][^+-]' | grep -E '(requestPairing|setMITM|bond_remove_key)' | grep -v 'preonic_bdiag_event'; then
  echo "Unexpected Bluetooth authentication logic change" >&2; exit 1
fi
echo "Verified: master BLE implementation + passive numeric telemetry"

make Keyboardio/Preonic
test -s output/Keyboardio/Preonic/default.zip
echo "Preonic firmware: output/Keyboardio/Preonic/default.zip"
