#!/usr/bin/env python3
"""Preonic-only authenticated BLE keyboard pairing.
Keep the installed core's existing bond and LESC handling. Fail closed if
any pinned source anchor differs. This is only applied by the Preonic build.
"""
from pathlib import Path
import sys

core = Path(sys.argv[1])
kaleidoscope = Path(__file__).resolve().parent.parent / "lib" / "Kaleidoscope"

def patch(path, changes):
    source = path.read_text()
    for before, after in changes:
        count = source.count(before)
        if count != 1:
            raise SystemExit(f"{path}: expected one match, got {count}: {before[:75]!r}")
        source = source.replace(before, after, 1)
    path.write_text(source)
    print("patched", path)

patch(core / "libraries/Bluefruit52Lib/src/BLESecurity.h", [
    ("#include \"bluefruit_common.h\"",
     "#include <atomic>\n#include \"bluefruit_common.h\""),
    ("    void setMITM(bool enabled);",
     "    void setMITM(bool enabled);\n\n    // Nonblocking passkey entry, explicitly enabled by the keyboard driver.\n    void enableKeyboardPasskeyEntry(void);\n    uint32_t pendingKeyboardPasskey(void) const { return _keyboard_passkey.load(); }\n    bool replyKeyboardPasskey(uint32_t request, const uint8_t* digits);"),
    ("    ble_gap_sec_params_t _sec_param;",
     "    ble_gap_sec_params_t _sec_param;\n    bool _keyboard_passkey_enabled = false;\n    uint16_t _keyboard_passkey_generation = 0;\n    std::atomic<uint32_t> _keyboard_passkey{0};\n    void clearKeyboardPasskey(uint16_t conn_hdl);"),
])

patch(core / "libraries/Bluefruit52Lib/src/BLESecurity.cpp", [
    ("#include \"bluefruit.h\"",
     "#include \"bluefruit.h\"\n#include <FreeRTOS.h>\n#include <task.h>"),
    ("/* Resolvable Address = Hash (24 bit) | Random (24 bit)",
     "void BLESecurity::enableKeyboardPasskeyEntry(void)\n{\n  setIOCaps(false, false, true);\n  setMITM(true);\n  _keyboard_passkey_enabled = true;\n}\n\nvoid BLESecurity::clearKeyboardPasskey(uint16_t conn_hdl)\n{\n  uint32_t request = _keyboard_passkey.load();\n  if (request && static_cast<uint16_t>(request) == conn_hdl)\n    _keyboard_passkey.compare_exchange_strong(request, 0);\n}\n\nbool BLESecurity::replyKeyboardPasskey(uint32_t request, const uint8_t* digits)\n{\n  if (!request) return false;\n  if (digits)\n    for (uint8_t i = 0; i < BLE_GAP_PASSKEY_LEN; ++i)\n      if (digits[i] < '0' || digits[i] > '9') return false;\n  // Serialize the claim/reply with the BLE event task. The SoftDevice SVC\n  // does not wait for the user or block the application event task.\n  vTaskSuspendAll();\n  uint32_t expected = request;\n  bool claimed = _keyboard_passkey.compare_exchange_strong(expected, 0);\n  uint32_t result = NRF_ERROR_INVALID_STATE;\n  if (claimed)\n    result = sd_ble_gap_auth_key_reply(static_cast<uint16_t>(request),\n        digits ? BLE_GAP_AUTH_KEY_TYPE_PASSKEY : BLE_GAP_AUTH_KEY_TYPE_NONE, digits);\n  xTaskResumeAll();\n  return result == NRF_SUCCESS;\n}\n\n/* Resolvable Address = Hash (24 bit) | Random (24 bit)"),
    ("    case BLE_GAP_EVT_SEC_PARAMS_REQUEST:\n    {",
     "    case BLE_GAP_EVT_DISCONNECTED:\n      clearKeyboardPasskey(conn_hdl);\n      break;\n\n    case BLE_GAP_EVT_SEC_PARAMS_REQUEST:\n    {\n      clearKeyboardPasskey(conn_hdl);"),
    ("      if (_passkey_req_cb)\n      {\n        ada_callback(NULL, 0, _passkey_request_callback_dfr, _passkey_req_cb, conn_hdl);\n      }",
     "      if (_keyboard_passkey_enabled && conn->getRole() == BLE_GAP_ROLE_PERIPH &&\n          evt->evt.gap_evt.params.auth_key_request.key_type == BLE_GAP_AUTH_KEY_TYPE_PASSKEY)\n      {\n        if (++_keyboard_passkey_generation == 0) ++_keyboard_passkey_generation;\n        _keyboard_passkey.store((static_cast<uint32_t>(_keyboard_passkey_generation) << 16) | conn_hdl);\n      }\n      else if (_passkey_req_cb)\n      {\n        ada_callback(NULL, 0, _passkey_request_callback_dfr, _passkey_req_cb, conn_hdl);\n      }"),
    ("    case BLE_GAP_EVT_AUTH_STATUS:\n    {",
     "    case BLE_GAP_EVT_AUTH_STATUS:\n    {\n      clearKeyboardPasskey(conn_hdl);"),
])

patch(kaleidoscope / "src/kaleidoscope/driver/ble/Bluefruit.h", [
    ("  kaleidoscope::EventHandlerResult onKeyEvent(kaleidoscope::KeyEvent &event);",
     "  kaleidoscope::EventHandlerResult onKeyEvent(kaleidoscope::KeyEvent &event);\n  bool handlePairingKey(const kaleidoscope::KeyEvent &event);"),
])

patch(kaleidoscope / "src/kaleidoscope/driver/ble/Bluefruit.cpp", [
    ("  Bluefruit.Security.setSecuredCallback(BLEBluefruit::secured_cb);",
     "  // Advertise the keyboard's actual IO capability before any connection.\n  Bluefruit.Security.enableKeyboardPasskeyEntry();\n  Bluefruit.Security.setSecuredCallback(BLEBluefruit::secured_cb);"),
    ("  Bluefruit.Security.setMITM(true);\n}",
     "  // Security capabilities were configured before advertising.\n}"),
    ("// Event handler for BLE-specific key events",
     "// Passkeys are local authentication input, not HID reports. This runs\n// only in the main physical-key event path, never in a BLE callback.\nbool BLEBluefruit::handlePairingKey(const kaleidoscope::KeyEvent &event) {\n  static uint32_t active_request = 0;\n  static uint8_t digits[BLE_GAP_PASSKEY_LEN] = {};\n  static uint8_t count = 0;\n  const uint32_t request = Bluefruit.Security.pendingKeyboardPasskey();\n  if (request != active_request) {\n    memset(digits, 0, sizeof(digits));\n    count = 0;\n    active_request = request;\n  }\n  if (!request) return false;\n\n  const Key key = event.key;\n  const uint16_t value = key.getRaw();\n  int8_t digit = -1;\n  if (value >= Key_1.getRaw() && value <= Key_9.getRaw())\n    digit = value - Key_1.getRaw() + 1;\n  else if (value == Key_0.getRaw() || value == Key_Keypad0.getRaw())\n    digit = 0;\n  else if (value >= Key_Keypad1.getRaw() && value <= Key_Keypad9.getRaw())\n    digit = value - Key_Keypad1.getRaw() + 1;\n\n  if (digit >= 0) {\n    if (count < BLE_GAP_PASSKEY_LEN) digits[count++] = '0' + digit;\n  } else if (key == Key_Backspace || key == Key_KeypadBackspace) {\n    if (count) digits[--count] = 0;\n  } else if (key == Key_Escape ||\n             ((key == Key_Enter || key == Key_KeypadEnter) && count == BLE_GAP_PASSKEY_LEN)) {\n    Bluefruit.Security.replyKeyboardPasskey(request, key == Key_Escape ? nullptr : digits);\n    memset(digits, 0, sizeof(digits));\n    count = 0;\n    active_request = 0;\n  }\n  // Do not let authentication digits (or other keys pressed during entry)\n  // escape to the HID transport, macros or other key handlers.\n  return true;\n}\n\n// Event handler for BLE-specific key events"),
])

patch(kaleidoscope / "src/kaleidoscope/Runtime.cpp", [
    ("  // Run the plugin event handlers\n  auto result = Hooks::onKeyswitchEvent(event);",
     "  // Preonic passkey entry must precede plugins and normal HID output.\n  // Mask only newly pressed physical keys; their later releases are already\n  // handled by the normal Key_Masked path, even after authentication ends.\n  if (keyToggledOn(event.state) && !keyIsInjected(event.state) &&\n      device().ble().handlePairingKey(event)) {\n    live_keys.mask(event.addr);\n    return;\n  }\n\n  // Run the plugin event handlers\n  auto result = Hooks::onKeyswitchEvent(event);"),
])

