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
        '  void updateBatteryStatus(uint16_t voltage_mv) {\n    // Get current time',
        '  void updateBatteryStatus(uint16_t voltage_mv) {\n'
        '    // An uninitialized MAX17048 returns 0. Do not treat read errors as shutdown.\n'
        '    if (voltage_mv == 0 || voltage_mv > 5000) return;\n'
        '    // Get current time'
    ),
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


# Diagnostic hooks only: BLE decisions and normal USB/BLE switching are untouched.
# Events are recorded by a nonblocking RAM ring in the Preonic sketch. No BLE
# callback prints to USB; the buffered events are drained after CDC DTR opens.
ble = root / "src/kaleidoscope/driver/ble/Bluefruit.cpp"
patch(ble, [
    (
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);',
        '  preonic_bdiag_event(1, current_device_id, conn->getPeerAddr().addr_type);\n'
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);'
    ),
    (
        'void BLEBluefruit::secured_cb(uint16_t conn_handle) {',
        'void BLEBluefruit::secured_cb(uint16_t conn_handle) {\n'
        '  preonic_bdiag_event(2, conn_handle, 0);'
    ),
    (
        '      conn->requestPairing();',
        '      preonic_bdiag_event(3, current_device_id, 0);\n'
        '      conn->requestPairing();'
    ),
    (
        '  DEBUG_BLE_MSG("Setting host connection mode to BLE");\n'
        '  kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);',
        '  // Do not steal the USB HID target when USB data is mounted.\n'
        '  // Keep BLE security and connection state untouched.\n'
        '  if (!kaleidoscope::Runtime.device().mcu().USBDataConnected()) {\n'
        '    kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);\n'
        '  }'
    ),
    (
        'void BLEBluefruit::disconnect_cb(uint16_t conn_handle, uint8_t reason) {',
        'void BLEBluefruit::disconnect_cb(uint16_t conn_handle, uint8_t reason) {\n'
        '  preonic_bdiag_event(4, conn_handle, reason);'
    ),
    (
        'void BLEBluefruit::startDiscoverableAdvertising() {',
        'void BLEBluefruit::startDiscoverableAdvertising() {\n'
        '  preonic_bdiag_event(5, current_device_id, 0);'
    ),
])
# Prototype visible to this translation unit; no changes to Bluefruit.h.
ble_source = ble.read_text()
ble_source = '#include <stdint.h>\nextern "C" void preonic_bdiag_event(uint16_t, uint16_t, uint16_t);\n' + ble_source
ble.write_text(ble_source)

# Keep one fixed-size RAM buffer across BLE mode. No flash wear, no secret keys,
# no serial I/O in BLE callbacks. Each record is published last via atomic seq.
sketch_diag = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/examples/Devices/Keyboardio/Preonic/Preonic.ino"
bdiag_code = r'''
// Preonic BLE diagnostic ring (RAM only, approximately 1.5 KiB).
// Events: 1 CONNECT(slot,peer-type), 2 SECURED_CB(handle), 3 PAIR_REQ(slot),
// 4 DISCONNECT(handle,reason), 5 PAIR_MODE(slot), 10 SEC_PARAMS_REQUEST,
// 11 AUTH_STATUS(code,bonded), 12 SEC_INFO_STORED, 13 SEC_INFO_MISSING,
// 14 SEC_UPDATE(mode,level), 15 BOND_LOOKUP(type,found).
namespace {
struct BDiagRecord {
  volatile uint32_t published;
  uint32_t at_ms;
  uint16_t event;
  uint16_t a;
  uint16_t b;
};
static constexpr uint32_t BDIAG_CAPACITY = 128;
static BDiagRecord bdiag_ring[BDIAG_CAPACITY];
static uint32_t bdiag_head = 0;
static uint8_t bdiag_lock = 0; // Nonblocking cross-context ring exclusion.
static uint32_t bdiag_cursor = 0;
static bool bdiag_usb_ready = false;
}
extern "C" void preonic_bdiag_event(uint16_t event, uint16_t a, uint16_t b) {
  if (__atomic_test_and_set(&bdiag_lock, __ATOMIC_ACQUIRE)) return;
  uint32_t seq = __atomic_add_fetch(&bdiag_head, 1u, __ATOMIC_RELAXED);
  BDiagRecord &slot = bdiag_ring[(seq - 1u) % BDIAG_CAPACITY];
  __atomic_store_n(&slot.published, 0u, __ATOMIC_RELAXED);
  slot.at_ms = millis();
  slot.event = event;
  slot.a = a;
  slot.b = b;
  __atomic_store_n(&slot.published, seq, __ATOMIC_RELEASE);
  __atomic_clear(&bdiag_lock, __ATOMIC_RELEASE);
}
static void preonic_bdiag_drain() {
  // DTR must be raised by the serial monitor. No USB -> no work.
  if (!Serial) {
    bdiag_usb_ready = false;
    return;
  }
  if (!bdiag_usb_ready) {
    // Defer session initialization until the CDC TX endpoint has space.
    if (Serial.availableForWrite() < 32) return;
    bdiag_usb_ready = true;
    uint32_t head = __atomic_load_n(&bdiag_head, __ATOMIC_ACQUIRE);
    bdiag_cursor = head > BDIAG_CAPACITY ? head - BDIAG_CAPACITY : 0;
    Serial.println("[BDIAG] READY v2");
  }
  // Drain at most one record per keyboard cycle, no blocking in BLE callback.
  uint32_t head = __atomic_load_n(&bdiag_head, __ATOMIC_ACQUIRE);
  if (bdiag_cursor >= head || Serial.availableForWrite() < 60) return;
  if (head - bdiag_cursor > BDIAG_CAPACITY) {
    bdiag_cursor = head - BDIAG_CAPACITY;
    Serial.println("[BDIAG] OVERFLOW oldest events lost");
  }
  // Snapshot a complete record under the same short lock as the writer.
  // Never hold the lock during USB serial output.
  if (__atomic_test_and_set(&bdiag_lock, __ATOMIC_ACQUIRE)) return;
  uint32_t wanted = bdiag_cursor + 1u;
  BDiagRecord &slot = bdiag_ring[(wanted - 1u) % BDIAG_CAPACITY];
  if (slot.published != wanted) {
    __atomic_clear(&bdiag_lock, __ATOMIC_RELEASE);
    return;
  }
  uint32_t at_ms = slot.at_ms;
  uint16_t event = slot.event, a = slot.a, b = slot.b;
  __atomic_clear(&bdiag_lock, __ATOMIC_RELEASE);
  Serial.print("[BDIAG] ms=");
  Serial.print(at_ms);
  Serial.print(" event=");
  Serial.print(event);
  Serial.print(" a=");
  Serial.print(a);
  Serial.print(" b=");
  Serial.println(b);
  bdiag_cursor = wanted;
}

// Manual fallback when a PC terminal doesn't raise CDC DTR. Fn+P types the
// last 24 numeric events into the active application via USB keyboard HID.
// This is opt-in only and does not depend on USB CDC being connected.
static bool bdiag_hid_dump_active = false;
static uint32_t bdiag_hid_cursor = 0;
static uint32_t bdiag_hid_end = 0;
static void preonic_bdiag_startHidDump() {
  uint32_t head = __atomic_load_n(&bdiag_head, __ATOMIC_ACQUIRE);
  bdiag_hid_cursor = (head > 24u) ? (head - 24u) : 0u;
  bdiag_hid_end = head;
  bdiag_hid_dump_active = true;
}
static void preonic_bdiag_drainHid() {
  if (!bdiag_hid_dump_active ||
      kaleidoscope::Runtime.device().getHostConnectionMode() != MODE_USB) return;
  if (bdiag_hid_cursor >= bdiag_hid_end) {
    Macros.type(PSTR("[BDIAG] END\n"));
    bdiag_hid_dump_active = false;
    return;
  }
  if (__atomic_test_and_set(&bdiag_lock, __ATOMIC_ACQUIRE)) return;
  uint32_t seq = bdiag_hid_cursor + 1u;
  BDiagRecord &slot = bdiag_ring[(seq - 1u) % BDIAG_CAPACITY];
  bool valid = slot.published == seq;
  uint32_t time_ms = valid ? slot.at_ms : 0;
  uint16_t event = valid ? slot.event : 0;
  uint16_t a = valid ? slot.a : 0;
  uint16_t b = valid ? slot.b : 0;
  __atomic_clear(&bdiag_lock, __ATOMIC_RELEASE);
  char line[64];
  if (valid) {
    snprintf(line, sizeof(line), "[BDIAG] %lu %u %u %u\n",
             (unsigned long)time_ms, event, a, b);
  } else {
    snprintf(line, sizeof(line), "[BDIAG] overwritten\n");
  }
  // Type one line per keyboard loop. The user explicitly triggered this dump.
  Macros.type(line);
  bdiag_hid_cursor = seq;
}

'''
patch(sketch_diag, [
    ('void setup() {\n  Kaleidoscope.setup();', bdiag_code + 'void setup() {\n  Kaleidoscope.setup();'),
    ('void loop() {\n  Kaleidoscope.loop();', 'void loop() {\n  Kaleidoscope.loop();\n  preonic_bdiag_drain();'),
])



# Automatic USB switching must preserve bond writes while not blocking
# USB attach. BLE disconnection and re-advertising are serviced from loop(),
# never by sleeping inside an asynchronous BLE callback.
ble_header = root / "src/kaleidoscope/driver/ble/Bluefruit.h"
patch(ble_header, [
    (
        '  static void disconnect();',
        '  static void disconnect();\n'
        '  static void requestGracefulDisconnect();\n'
        '  static void servicePendingActions();'
    ),
    (
        '  void scheduleSafeDisconnect();',
        '  // Deferred safety state lives in Bluefruit.cpp.'
    ),
])
patch(switcher, [
    (
        '    Runtime.device().ble().disconnect();',
        '    Runtime.device().ble().requestGracefulDisconnect();'
    ),
])
patch(ble, [
    (
        '// Add static variable to track sleep start time\nstatic uint32_t sleep_start_time = 0;',
        '// Add static variable to track sleep start time\nstatic uint32_t sleep_start_time = 0;\n'
        '// Deferred operations avoid blocking SoftDevice callbacks and USB attach.\n'
        'static volatile bool preonic_disconnect_pending = false;\n'
        'static volatile uint32_t preonic_disconnect_at = 0;\n'
        'static volatile bool preonic_advertise_pending = false;\n'
        'static volatile uint32_t preonic_advertise_at = 0;\n'
        'static uint8_t preonic_advertise_failures = 0;'
    ),
    (
        '        if (rssi == 127 || rssi < -90) {\n'
        '          DEBUG_BLE_MSG("Connection validation failed: invalid RSSI=", rssi);\n'
        '          connection_is_stale = true;\n'
        '        } else {\n'
        '          // Try to get connection parameters - if this fails, connection is likely dead\n'
        '          uint16_t interval = conn->getConnectionInterval();\n'
        '          if (interval == 0 || interval > 1000) {  // Sanity check on interval\n'
        '            DEBUG_BLE_MSG("Connection validation failed: invalid interval=", interval);\n'
        '            connection_is_stale = true;\n'
        '          } else {\n'
        '            DEBUG_BLE_MSG("Connection validated: RSSI=", rssi, "dBm, interval=", interval);\n'
        '          }\n'
        '        }',
        '        // Weak/unknown RSSI does not prove a dead encrypted HID link.\n'
        '        uint16_t interval = conn->getConnectionInterval();\n'
        '        if (interval == 0 || interval > 1000) {\n'
        '          DEBUG_BLE_MSG("Connection validation failed: invalid interval=", interval);\n'
        '          connection_is_stale = true;\n'
        '        } else {\n'
        '          DEBUG_BLE_MSG("Connection parameters valid: RSSI=", rssi, " interval=", interval);\n'
        '        }'
    ),
    (
        """  // Error 0x516 indicates advertising failed - this can happen during rapid state changes
  // We track consecutive failures to prevent getting stuck in a retry loop
  static uint8_t failure_count      = 0;
  static uint32_t last_failure_time = 0;

  if (reason == 0x516) {
    DEBUG_BLE_MSG("Nordic error 0x516: Advertising procedure failed");

    // Reset failure count if more than 5 seconds have passed
    uint32_t now = millis();
    if ((now - last_failure_time) > 5000) {
      failure_count = 0;
    }
    last_failure_time = now;

    if (++failure_count >= 3) {
      DEBUG_BLE_MSG("Multiple advertising failures detected, stopping retry loop");
      failure_count = 0;
      Bluefruit.Advertising.stop();
      delay(500);
      return;
    }
  }

  switch (reason) {
  case BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION:
    DEBUG_BLE_MSG("Remote device terminated connection");

    // For devices that have multiple remote terminations, use a more conservative approach
    static uint8_t consecutive_remote_terminations = 0;
    consecutive_remote_terminations++;

    if (consecutive_remote_terminations >= 2) {
      DEBUG_BLE_MSG("Multiple consecutive remote terminations detected, using conservative reconnection");
      delay(500);  // Longer delay for problematic devices

      // Reset advertising parameters to be more conservative
      Bluefruit.Advertising.setInterval(80, 160);  // Slower advertising
      Bluefruit.Advertising.setFastTimeout(10);    // Shorter fast mode
    } else {
      delay(100);  // Normal delay
    }

    startDiscoverableAdvertising();
    break;

  case BLE_HCI_LOCAL_HOST_TERMINATED_CONNECTION:
    DEBUG_BLE_MSG("Local device terminated connection. Don't assume we should do something.");
    consecutive_remote_terminations = 0;  // Reset counter on local termination
    break;

  case BLE_HCI_REMOTE_DEV_TERMINATION_DUE_TO_POWER_OFF:
  case BLE_HCI_CONNECTION_TIMEOUT:
  default:
    DEBUG_BLE_MSG("Attempting to reconnect to last device");
    consecutive_remote_terminations = 0;  // Reset counter on other disconnect types

    if (current_device_id > 0) {
      delay(250);  // Give time for cleanup
      startConnectableAdvertising();
    }
    break;
  }""",
        """  // The disconnect reason is 8-bit; comparing it to Nordic error
  // 0x516 was impossible. Advertising-start errors are handled at their source.
  // A normal remote disconnect must NEVER remove the bond or start pairing.
  if (reason == BLE_HCI_LOCAL_HOST_TERMINATED_CONNECTION) {
    preonic_advertise_pending = false;
  } else if (current_device_id > 0) {
    preonic_advertise_at = millis() + 150;
    preonic_advertise_pending = true;
  }"""
    ),
    (
        '  if (!Bluefruit.Advertising.start(ADVERTISING_TIMEOUT)) {\n'
        '    DEBUG_BLE_MSG("Failed to start advertising");\n'
        '  }\n'
        '  DEBUG_BLE_MSG("Started connectable advertising");',
        '  if (!Bluefruit.Advertising.start(ADVERTISING_TIMEOUT)) {\n'
        '    DEBUG_BLE_MSG("Failed to start connectable advertising; scheduling retry");\n'
        '    preonic_bdiag_event(16, preonic_advertise_failures, 0);\n'
        '    if (preonic_advertise_failures < 5) ++preonic_advertise_failures;\n'
        '    preonic_advertise_at = millis() + 250 * (1u << preonic_advertise_failures);\n'
        '    preonic_advertise_pending = true;\n'
        '    return;\n'
        '  }\n'
        '  preonic_advertise_failures = 0;\n'
        '  DEBUG_BLE_MSG("Started connectable advertising");'
    ),
    (
        '    kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);\n'
        '    kaleidoscope::Runtime.device().hid().keyboard().releaseAllKeys();',
        '    uint8_t saved_mode = kaleidoscope::Runtime.device().getHostConnectionMode();\n'
        '    kaleidoscope::Runtime.device().setHostConnectionMode(MODE_BLE);\n'
        '    kaleidoscope::Runtime.device().hid().keyboard().releaseAllKeys();\n'
        '    kaleidoscope::Runtime.device().setHostConnectionMode(saved_mode);'
    ),
    (
        '    scheduleSafeDisconnect();',
        '    requestGracefulDisconnect();'
    ),
    (
        """void BLEBluefruit::scheduleSafeDisconnect() {
  uint32_t now = millis();
  if (bond_write_pending && ((int32_t)(bond_write_deadline_ms - now) > 0)) {
    uint32_t wait_ms = bond_write_deadline_ms - now;
    DEBUG_BLE_MSG("Delaying disconnect %ums to allow bond write", wait_ms);
    delay(wait_ms);
    bond_write_pending = false;
  }
  disconnect();
}""",
        """void BLEBluefruit::requestGracefulDisconnect() {
  uint32_t now = millis();
  if (bond_write_pending && ((int32_t)(bond_write_deadline_ms - now) > 0)) {
    // Keep the radio connected temporarily so the deferred bond save can finish.
    preonic_disconnect_at = bond_write_deadline_ms;
    preonic_disconnect_pending = true;
    return;
  }
  preonic_disconnect_pending = false;
  disconnect();
}

void BLEBluefruit::servicePendingActions() {
  uint32_t now = millis();
  if (preonic_disconnect_pending && (int32_t)(now - preonic_disconnect_at) >= 0) {
    preonic_disconnect_pending = false;
    bond_write_pending = false;
    if (Bluefruit.Periph.connected()) disconnect();
  }
  // The only automatic re-advertising path is the connectable/bond-preserving
  // one. Explicit pairing continues to use startDiscoverableAdvertising().
  if (preonic_advertise_pending && (int32_t)(now - preonic_advertise_at) >= 0) {
    preonic_advertise_pending = false;
    if (current_device_id > 0 && !Bluefruit.Periph.connected() &&
        !Bluefruit.Advertising.isRunning()) {
      startConnectableAdvertising();
    }
  }
}"""
    ),
])
patch(sketch_diag, [
    (
        'void loop() {\n  Kaleidoscope.loop();\n  preonic_bdiag_drain();',
        'void loop() {\n  Kaleidoscope.loop();\n'
        '  kaleidoscope::Runtime.device().ble().servicePendingActions();\n'
        '  preonic_bdiag_drain();'
    ),
])
patch(sketch_diag, [
    (
        '      kaleidoscope::Runtime.device().ble().disconnect();',
        '      kaleidoscope::Runtime.device().ble().requestGracefulDisconnect();'
    ),
])


# Cancel stale deferred operations whenever the user explicitly changes radio
# intent; this prevents a pending reconnect from defeating BLE-OFF or PAIR.
patch(ble, [
    (
        '  preonic_bdiag_event(5, current_device_id, 0);\n',
        '  preonic_bdiag_event(5, current_device_id, 0);\n'
        '  preonic_advertise_pending = false;\n'
        '  preonic_disconnect_pending = false;\n'
    ),
    (
        'void BLEBluefruit::selectDevice(uint8_t device_id) {\n  if (device_id == 0)',
        'void BLEBluefruit::selectDevice(uint8_t device_id) {\n'
        '  preonic_advertise_pending = false;\n'
        '  preonic_disconnect_pending = false;\n'
        '  if (device_id == 0)'
    ),
    (
        'void BLEBluefruit::requestGracefulDisconnect() {\n  uint32_t now = millis();',
        'void BLEBluefruit::requestGracefulDisconnect() {\n'
        '  preonic_advertise_pending = false;\n'
        '  uint32_t now = millis();'
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
        '    if (voltage_mv == 0 || voltage_mv > 5000) return;',
        '    if (voltage_mv == 0 || voltage_mv > 5000) {\n'
        '      // Throttle failed I2C readings instead of retrying every scan cycle.\n'
        '      last_battery_check_time_ = millis();\n'
        '      return;\n'
        '    }'
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


# Default FUN+P = opt-in diagnostic dump as USB HID text when CDC DTR is off.
# Append macro ID rather than reordering persisted macro IDs.
patch(sketch_diag, [
    (
        '  MACRO_BATTERY_LEVEL  // Report current battery level',
        '  MACRO_BATTERY_LEVEL,  // Report current battery level\n'
        '  MACRO_DIAG_LOG'
    ),
    (
        '    Key_LEDEffectNext,___,           Consumer_VolumeIncrement,___,            ___,             ___,             ___,             ___,             ___,                        ___,             ___,             ___,',
        '    Key_LEDEffectNext,___,           Consumer_VolumeIncrement,___,            ___,             ___,             ___,             ___,             ___,                        ___,             M(MACRO_DIAG_LOG),             ___,'
    ),
    (
        'const macro_t *macroAction(uint8_t macro_id, KeyEvent &event) {',
        'static void preonic_bdiag_startHidDump();\n'
        'const macro_t *macroAction(uint8_t macro_id, KeyEvent &event) {'
    ),
    (
        '  case MACRO_BATTERY_LEVEL:\n    batteryLevelMacro(event.state);\n    break;',
        '  case MACRO_BATTERY_LEVEL:\n    batteryLevelMacro(event.state);\n    break;\n'
        '  case MACRO_DIAG_LOG:\n'
        '    if (keyToggledOn(event.state)) preonic_bdiag_startHidDump();\n'
        '    break;'
    ),
    (
        '  preonic_bdiag_drain();',
        '  preonic_bdiag_drain();\n  preonic_bdiag_drainHid();'
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
