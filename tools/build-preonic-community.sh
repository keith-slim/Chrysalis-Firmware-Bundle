#!/usr/bin/env bash
# Preonic-only rebuild from the exact master Kaleidoscope and installed official core.
# Preserve encryption, bonds and slot addressing; add keyboard passkey entry only.
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

# Keep the Run #63 USB/BLE auto-switching patch unchanged. Restore only
# defensive bond file handling in the installed official nRF52 core.
# No diagnostic hooks, RAM log, or USB serial output are added.
core_root="${ARDUINO_DIRECTORIES_DATA:-$PWD/.arduino/data}/packages/keyboardio/hardware/nrf52"
mapfile -t cores < <(find "$core_root" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/libraries/Bluefruit52Lib/src/utility/bonding.cpp' \; -print)
test "${#cores[@]}" -eq 1
python3 tools/patch-preonic-bond-safety.py "${cores[0]}"
python3 tools/patch-preonic-runtime.py
python3 tools/patch-preonic-pr1540.py
python3 tools/patch-preonic-no-deep-sleep.py

# Verify actual core patch and absence of diagnostic instrumentation.
bond_file="${cores[0]}/libraries/Bluefruit52Lib/src/utility/bonding.cpp"
grep -Fq 'InternalFS.rename(tmp_filename, filename)' "$bond_file"
grep -Fq 'name_conn && name_conn->connected()' "$bond_file"
if grep -Fq 'preonic_bdiag_event' "$bond_file"; then
  echo "Unexpected diagnostic instrumentation in the official core" >&2
  exit 1
fi

preonic_sketch="lib/Kaleidoscope/plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
grep -Fq '  Keyclick.enable();' "$preonic_sketch"
if grep -Fq '  Keyclick.disable();' "$preonic_sketch"; then
  echo "Unexpected Keyclick.disable() remains" >&2
  exit 1
fi

# Verify the upstream PR #1540 reconnect changes before layering pairing fixes.
# USB auto-switching and bonding logic remain unchanged.
ble_file="lib/Kaleidoscope/src/kaleidoscope/driver/ble/Bluefruit.cpp"
grep -Fq 'if (!Bluefruit.Periph.connected() && !Bluefruit.Advertising.isRunning())' "$ble_file"
grep -Fq 'Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE)' "$ble_file"
grep -Fq 'if (!Bluefruit.Advertising.start(0))' "$ble_file"
git -C lib/Kaleidoscope diff --exit-code -- src/kaleidoscope/driver/ble/Bluefruit.h
git -C lib/Kaleidoscope diff --check -- src/kaleidoscope/driver/ble/Bluefruit.cpp
echo "Verified: upstream PR #1540 baseline; USB switch and bond safety preserved"

# Apply keyboard authentication changes only after baseline verification.
python3 tools/patch-preonic-keyboard-pairing.py "${cores[0]}"
grep -Fq "Bluefruit.Security.enableKeyboardPasskeyEntry();" "$ble_file"
grep -Fq "setIOCaps(false, false, true);" "${cores[0]}/libraries/Bluefruit52Lib/src/BLESecurity.cpp"
grep -Fq "device().ble().handlePairingKey(event)" lib/Kaleidoscope/src/kaleidoscope/Runtime.cpp
git -C lib/Kaleidoscope diff --check -- src/kaleidoscope/driver/ble/Bluefruit.cpp src/kaleidoscope/driver/ble/Bluefruit.h src/kaleidoscope/Runtime.cpp
echo "Verified: nonblocking keyboard passkey path enabled; LESC and MITM retained"

# Check diagnostic scope: the one inactivity sleep call is compiled out.
# Leave battery voltage shutdown and its protections enabled.
preonic_header="lib/Kaleidoscope/plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/src/kaleidoscope/device/keyboardio/Preonic.h"
grep -Fq '#if 0  // DIAGNOSTIC: disable automatic deep sleep only' "$preonic_header"
grep -Fq '#endif  // DIAGNOSTIC: restore this block after isolation test' "$preonic_header"
grep -Fq '    if (shouldEnterDeepSleep()) {' "$preonic_header"
grep -Fq 'if (isBatteryBelowShutdownThreshold(voltage_mv))' "$preonic_header"
git -C lib/Kaleidoscope diff --check -- plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/src/kaleidoscope/device/keyboardio/Preonic.h
echo "Verified: inactivity deep sleep disabled only; battery low-voltage cutoff preserved"

make Keyboardio/Preonic
test -s output/Keyboardio/Preonic/default.zip
echo "Preonic firmware: output/Keyboardio/Preonic/default.zip"
