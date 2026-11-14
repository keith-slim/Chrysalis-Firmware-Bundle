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

# Enable normal keyclick feedback at boot. Fun+Z still toggles it as before.
# CI verification: use the exact pinned community sketch's startup setting.
sketch = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
patch(sketch, [
    (
        '  // Disable Keyclick by default\n  Keyclick.disable();',
        '  // Enable Keyclick by default; users can still toggle it with Fun+Z.\n  Keyclick.enable();'
    ),
])
