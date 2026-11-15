#!/usr/bin/env python3
"""Apply only keyboardio/Kaleidoscope PR #1540 to the pinned Preonic BLE driver.

Changes: preserve TX power while advertising in sleep; reconnect to bonded host
after remote disconnect; advertise in general mode until connected.
Does not alter USB switching, pairing/bond storage, logging, or other BLE code.
Fail fast if the expected upstream source differs.
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "lib" / "Kaleidoscope"
driver = root / "src/kaleidoscope/driver/ble/Bluefruit.cpp"
source = driver.read_text(encoding="utf-8")


def replace_once(before, after):
    global source
    matches = source.count(before)
    if matches != 1:
        raise SystemExit(f"{driver}: PR #1540 source anchor count {matches}, expected 1: {before[:85]!r}")
    source = source.replace(before, after, 1)


# PR #1540: Do not make an advertising keyboard invisible by dropping TX to -40 dBm.
replace_once(
    "  // If not connected, reduce TX power to minimum\n"
    "  if (!Bluefruit.Periph.connected()) {",
    "  // If disconnected but still advertising, retain reconnection TX power.\n"
    "  if (!Bluefruit.Periph.connected() && !Bluefruit.Advertising.isRunning()) {",
)

# PR #1540: Remote-initiated disconnect should resume bonded-host advertising.
# Keep the normal pairing entry path startDiscoverableAdvertising() untouched.
replace_once(
    "      delay(100);  // Normal delay\n"
    "    }\n\n"
    "    startDiscoverableAdvertising();\n"
    "    break;\n\n"
    "  case BLE_HCI_LOCAL_HOST_TERMINATED_CONNECTION:",
    "      delay(100);  // Normal delay\n"
    "    }\n\n"
    "    startConnectableAdvertising();\n"
    "    break;\n\n"
    "  case BLE_HCI_LOCAL_HOST_TERMINATED_CONNECTION:",
)

# PR #1540: General discoverable flags; do not stop reconnection advertising at 60s.
# Pairing advertising timeout remains unchanged.
replace_once(
    "void BLEBluefruit::startConnectableAdvertising() {\n"
    "  stopAdvertising();\n"
    "  configureAdvertising();\n"
    "  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_LIMITED_DISC_MODE);\n\n"
    '  DEBUG_BLE_MSG("Attempting to start advertising...");\n'
    "  if (!Bluefruit.Advertising.start(ADVERTISING_TIMEOUT)) {",
    "void BLEBluefruit::startConnectableAdvertising() {\n"
    "  stopAdvertising();\n"
    "  configureAdvertising();\n"
    "  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);\n\n"
    '  DEBUG_BLE_MSG("Attempting to start advertising...");\n'
    "  if (!Bluefruit.Advertising.start(0)) {  // Reconnect advertising until connected",
)

driver.write_text(source, encoding="utf-8")
print("Applied upstream PR #1540 (BLE reconnect only):", driver.relative_to(root))
