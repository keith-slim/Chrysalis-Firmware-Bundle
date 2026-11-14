#!/usr/bin/env python3
"""Preonic-only runtime safety fixes layered over pinned community sources.
All replacements are asserted to match exactly once; unexpected upstream changes fail CI.
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "lib" / "Kaleidoscope"
preonic = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/src/kaleidoscope"

def patch(path, changes):
    source = path.read_text()
    for before, after in changes:
        count = source.count(before)
        if count != 1:
            raise SystemExit(f"{path}: expected one match, got {count}: {before[:75]!r}")
        source = source.replace(before, after, 1)
    path.write_text(source)
    print("patched", path.relative_to(root))

switcher = preonic / "plugin/USBAutoSwitcher.cpp"
patch(switcher, [
    (
        'if (!Runtime.device().mcu().USBPowerDetected()) {\n      switchToFallbackBLE();',
        'if (!Runtime.device().mcu().USBDataConnected()) {\n      switchToFallbackBLE();'
    ),
    (
        'if (current_host_mode_ != MODE_USB) {\n        switchToUSB();',
        'if (getCurrentHostMode() != MODE_USB) {\n        switchToUSB();'
    ),
    (
        'if (current_host_mode_ == MODE_USB) {\n        switchToFallbackBLE();',
        'if (getCurrentHostMode() == MODE_USB) {\n        switchToFallbackBLE();'
    ),
    (
        '    fallback_ble_device_ = device_id;\n    current_host_mode_   = MODE_BLE;',
        '    fallback_ble_device_ = device_id;\n    // A selected BLE slot is not proof the active transport is BLE.'
    ),
])

ble = root / "src/kaleidoscope/driver/ble/Bluefruit.cpp"
patch(ble, [
    (
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);',
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);\n'
        '  if (Serial) {\n'
        '    Serial.print("[BDIAG] CONNECT slot=");\n'
        '    Serial.print(current_device_id);\n'
        '    Serial.print(" peer_type=");\n'
        '    Serial.println(conn->getPeerAddr().addr_type);\n'
        '  }'
    ),
    (
        'void BLEBluefruit::startDiscoverableAdvertising() {',
        'void BLEBluefruit::startDiscoverableAdvertising() {\n'
        '  if (Serial) Serial.println("[BDIAG] EXPLICIT_PAIR_MODE_START");'
    ),
    (
        '  DEBUG_BLE_MSG("ERROR: failed to set slot-specific address for slot ", slot_id);',
        '  if (Serial) { Serial.print("[BDIAG] SLOT_ADDR_SET_FAILED slot="); Serial.println(slot_id); }\n'
        '  DEBUG_BLE_MSG("ERROR: failed to set slot-specific address for slot ", slot_id);'
    ),
    (
        '    if (Bluefruit.setAddr(&slot_addr)) {\n      return;',
        '    if (Bluefruit.setAddr(&slot_addr)) {\n'
        '      if (Serial) { Serial.print("[BDIAG] SLOT_ADDR_OK slot="); Serial.println(slot_id); }\n'
        '      return;'
    ),
    (
        'if (rssi == 127 || rssi < -90) {',
        'if (rssi == 127) {'
    ),
    (
        '  DEBUG_BLE_MSG("Setting host connection mode to BLE");\n  kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);',
        '  // A background BLE security callback must not steal an active USB host.\n'
        '  if (!(kaleidoscope::Runtime.device().mcu().USBDataConnected() &&\n'
        '        kaleidoscope::Runtime.device().getHostConnectionMode() == MODE_USB)) {\n'
        '    DEBUG_BLE_MSG("Setting host connection mode to BLE");\n'
        '    kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);\n'
        '  }'
    ),
])

header = preonic / "device/keyboardio/Preonic.h"
patch(header, [
    (
        '      // Update battery monitoring - this handles both warning and shutdown thresholds\n'
        '      // Use the MAX17048 battery gauge to provide the voltage reading\n'
        '      uint16_t battery_voltage = batteryGauge().getVoltage();\n'
        '      updateBatteryStatus(battery_voltage);\n'
        '      last_battery_update_ = now;',
        '      last_battery_update_ = now;'
    ),
    (
        '    // Handle any pending GPIOTE events',
        '    // Run protection sampling independently of the slower BLE percentage update.\n'
        '    // updateBatteryStatus() still enforces BATTERY_CHECK_INTERVAL_MS.\n'
        '    if (now - last_battery_check_time_ >= BATTERY_CHECK_INTERVAL_MS) {\n'
        '      updateBatteryStatus(batteryGauge().getVoltage());\n'
        '    }\n\n'
        '    // Handle any pending GPIOTE events'
    ),
])

cpp = preonic / "device/keyboardio/Preonic.cpp"
patch(cpp, [
    (
        '    speaker().playTone(1500, 100);\n'
        '    delay(100);\n'
        '    speaker().playTone(1500, 100);\n'
        '    delay(100);\n'
        '    speaker().playTone(1500, 100);',
        '    // One tone instead of blocking key scanning for 200ms.\n'
        '    speaker().playTone(1500, 100);'
    ),
])

# Diagnostic build: initialize USB CDC explicitly. nRF52 main.cpp only starts
# Serial automatically with CFG_DEBUG, which is normally off. Do not wait for
# a host here; the keyboard must still start when used wirelessly.
sketch_diag = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
patch(sketch_diag, [
    (
        'void setup() {\n  Kaleidoscope.setup();',
        'void setup() {\n  Serial.begin(115200);  // BDIAG: USB CDC available without CFG_DEBUG\n'
        '  Kaleidoscope.setup();'
    ),
    (
        'void loop() {\n  Kaleidoscope.loop();',
        'void loop() {\n'
        '  static bool bdiag_serial_ready = false;\n'
        '  if (Serial && !bdiag_serial_ready) {\n'
        '    Serial.println("[BDIAG] USB_SERIAL_READY baud=115200");\n'
        '    bdiag_serial_ready = true;\n'
        '  } else if (!Serial) {\n'
        '    bdiag_serial_ready = false;\n'
        '  }\n'
        '  Kaleidoscope.loop();'
    ),
])

# Enable normal keyclick feedback at boot. Fun+Z still toggles it as before.
# CI verification: use the exact pinned community sketch's startup setting.
sketch = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
patch(sketch, [
    (
        '  // Disable Keyclick by default\n  Keyclick.disable();',
        '  // Enable Keyclick by default; users can still toggle it with Fun+Z.\n  Keyclick.enable();'
    ),
])
