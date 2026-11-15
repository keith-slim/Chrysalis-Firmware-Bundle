#!/usr/bin/env python3
"""Preonic-only USB and battery fixes layered on master Kaleidoscope.
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

# Restore only battery voltage validation, warning scheduling and atomic
# rotary encoder taps from 8c8788e4. No BLE, USB mode, bond, or logging edits.
# An uninitialized gauge reports 0 mV. Never enter battery shutdown on
# invalid readings; throttle retries to the normal 10-second sampling interval.
patch(header, [
    (
        '  void updateBatteryStatus(uint16_t voltage_mv) {\n    // Get current time',
        '  void updateBatteryStatus(uint16_t voltage_mv) {\n'
        '    if (voltage_mv == 0 || voltage_mv > 5000) {\n'
        '      last_battery_check_time_ = millis();\n'
        '      return;\n'
        '    }\n'
        '    // Get current time'
    ),
])

# One event per encoder detent instead of two separately queued events.
# This guarantees press+release are processed together even when the matrix
# event queue is nearly full. It also halves encoder queue traffic.
scanner = root / "src/kaleidoscope/driver/keyscanner/NRF52KeyScanner.h"
patch(scanner, [
    (
        '    bool pressed : 1;\n  };',
        '    bool pressed : 1;\n    bool tap : 1;  // Atomic press+release from an encoder\n  };'
    ),
    (
        'bool queueKeyEvent(uint8_t row, uint8_t col, bool state) {\n'
        '    Event event                           = {row, col, state};',
        'bool queueKeyEvent(uint8_t row, uint8_t col, bool state, bool tap = false) {\n'
        '    Event event                           = {row, col, state, tap};'
    ),
    (
        '      updateMatrixScanKeyState();\n    }\n  }\n\n  uint8_t pressedKeyswitchCount()',
        '      updateMatrixScanKeyState();\n'
        '      if (event.tap) {\n'
        '        setMatrixState(event.row, event.col, false);\n'
        '        actOnMatrixScan();\n'
        '        updateMatrixScanKeyState();\n'
        '      }\n'
        '    }\n  }\n\n  uint8_t pressedKeyswitchCount()'
    ),
])
patch(header, [
    (
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].ccw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].ccw.col,\n'
        '                                     true);\n'
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].ccw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].ccw.col,\n'
        '                                     false);',
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].ccw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].ccw.col,\n'
        '                                     true, true);'
    ),
    (
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].cw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].cw.col,\n'
        '                                     true);\n'
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].cw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].cw.col,\n'
        '                                     false);',
        '      active_scanner_->queueKeyEvent(ENCODER_CONFIGS[encoder_index].cw.row,\n'
        '                                     ENCODER_CONFIGS[encoder_index].cw.col,\n'
        '                                     true, true);'
    ),
    (
        '          battery_status_ = BatteryStatus::Normal;\n'
        '          warning_active_ = false;',
        '          battery_status_ = BatteryStatus::Normal;'
    ),
    (
        '        battery_status_ = BatteryStatus::Normal;\n'
        '        warning_active_ = false;',
        '        battery_status_ = BatteryStatus::Normal;'
    ),
    (
        """    // Handle warning indication timing
    if (battery_status_ == BatteryStatus::Warning) {
      if (!warning_active_ && (now - last_warning_time_ >= WARNING_INTERVAL_MS)) {
        // Start a new warning period
        warning_active_    = true;
        last_warning_time_ = now;
        triggerBatteryWarning(true);
      } else if (warning_active_ && (now - last_warning_time_ >= WARNING_DURATION_MS)) {
        // End the current warning period
        warning_active_ = false;
        triggerBatteryWarning(false);
      }
    }
  }

 public:""",
        """  }

  // Warning LED/tone timing is independent from the 10s voltage/I2C sampling.
  void updateBatteryWarningIndicator(uint32_t now) {
    if (battery_status_ != BatteryStatus::Warning) {
      if (warning_active_) {
        warning_active_ = false;
        triggerBatteryWarning(false);
      }
      return;
    }
    if (!warning_active_ && now - last_warning_time_ >= WARNING_INTERVAL_MS) {
      warning_active_ = true;
      last_warning_time_ = now;
      triggerBatteryWarning(true);
    } else if (warning_active_ && now - last_warning_time_ >= WARNING_DURATION_MS) {
      warning_active_ = false;
      triggerBatteryWarning(false);
    }
  }

 public:"""
    ),
    (
        '    // Handle any pending GPIOTE events',
        '    updateBatteryWarningIndicator(now);\n\n'
        '    // Handle any pending GPIOTE events'
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
