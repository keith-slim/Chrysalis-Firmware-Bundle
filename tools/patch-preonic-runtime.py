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


# Diagnostic hooks only: BLE decisions and normal USB/BLE switching are untouched.
# Events are recorded by a nonblocking RAM ring in the Preonic sketch. No BLE
# callback prints to USB; the buffered events are drained after CDC DTR opens.
ble = root / "src/kaleidoscope/driver/ble/Bluefruit.cpp"
patch(ble, [
    (
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);',
        '  preonic_bdiag_event(1, current_device_id, conn->getPeerAddr().addr_type);\\n'
        '  DEBUG_BLE_MSG("Connection established, handle: ", conn_handle);'
    ),
    (
        'void BLEBluefruit::secured_cb(uint16_t conn_handle) {',
        'void BLEBluefruit::secured_cb(uint16_t conn_handle) {\\n'
        '  preonic_bdiag_event(2, conn_handle, 0);'
    ),
    (
        '      conn->requestPairing();',
        '      preonic_bdiag_event(3, current_device_id, 0);\\n'
        '      conn->requestPairing();'
    ),
    (
        'void BLEBluefruit::disconnect_cb(uint16_t conn_handle, uint8_t reason) {',
        'void BLEBluefruit::disconnect_cb(uint16_t conn_handle, uint8_t reason) {\\n'
        '  preonic_bdiag_event(4, conn_handle, reason);'
    ),
    (
        'void BLEBluefruit::startDiscoverableAdvertising() {',
        'void BLEBluefruit::startDiscoverableAdvertising() {\\n'
        '  preonic_bdiag_event(5, current_device_id, 0);'
    ),
])
# Prototype visible to this translation unit; no changes to Bluefruit.h.
ble_source = ble.read_text()
ble_source = '#include <stdint.h>\\nextern "C" void preonic_bdiag_event(uint16_t, uint16_t, uint16_t);\\n' + ble_source
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
static uint32_t bdiag_cursor = 0;
static bool bdiag_usb_ready = false;
}
extern "C" void preonic_bdiag_event(uint16_t event, uint16_t a, uint16_t b) {
  uint32_t seq = __atomic_add_fetch(&bdiag_head, 1u, __ATOMIC_RELAXED);
  BDiagRecord &slot = bdiag_ring[(seq - 1u) % BDIAG_CAPACITY];
  __atomic_store_n(&slot.published, 0u, __ATOMIC_RELAXED);
  slot.at_ms = millis();
  slot.event = event;
  slot.a = a;
  slot.b = b;
  __atomic_store_n(&slot.published, seq, __ATOMIC_RELEASE);
}
static void preonic_bdiag_drain() {
  // DTR must be raised by the serial monitor. No USB -> no work.
  if (!Serial) {
    bdiag_usb_ready = false;
    return;
  }
  if (!bdiag_usb_ready) {
    bdiag_usb_ready = true;
    uint32_t head = __atomic_load_n(&bdiag_head, __ATOMIC_ACQUIRE);
    bdiag_cursor = head > BDIAG_CAPACITY ? head - BDIAG_CAPACITY : 0;
    Serial.println("[BDIAG] RAM_LOG_READY v=1 events: 1=CONNECT 2=SECURED_CB 3=PAIR_REQ 4=DISCONNECT 5=PAIR_MODE 10=SEC_PARAMS 11=AUTH_STATUS 12=STORED_KEY 13=NO_KEY 14=SEC_UPDATE 15=BOND_LOOKUP");
  }
  // Drain at most one record per keyboard cycle, no blocking in BLE callback.
  uint32_t head = __atomic_load_n(&bdiag_head, __ATOMIC_ACQUIRE);
  if (bdiag_cursor >= head || Serial.availableForWrite() < 60) return;
  if (head - bdiag_cursor > BDIAG_CAPACITY) {
    bdiag_cursor = head - BDIAG_CAPACITY;
    Serial.println("[BDIAG] OVERFLOW oldest events lost");
  }
  uint32_t wanted = bdiag_cursor + 1u;
  BDiagRecord &slot = bdiag_ring[(wanted - 1u) % BDIAG_CAPACITY];
  if (__atomic_load_n(&slot.published, __ATOMIC_ACQUIRE) != wanted) return;
  uint32_t at_ms = slot.at_ms;
  uint16_t event = slot.event, a = slot.a, b = slot.b;
  if (__atomic_load_n(&slot.published, __ATOMIC_ACQUIRE) != wanted) return;
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

'''
patch(sketch_diag, [
    ('void setup() {\\n  Kaleidoscope.setup();', bdiag_code + 'void setup() {\\n  Kaleidoscope.setup();'),
    ('void loop() {\\n  Kaleidoscope.loop();', 'void loop() {\\n  Kaleidoscope.loop();\\n  preonic_bdiag_drain();'),
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
