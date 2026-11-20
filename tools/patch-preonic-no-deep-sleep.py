#!/usr/bin/env python3
"""Diagnostic Preonic build: disable automatic inactivity deep sleep only.

Keep BLE reconnect (#1540), USB/BLE switching, battery voltage cutoff,
bond persistence, and all other behavior unchanged. NOT for long-term use:
battery consumption will be higher while this test patch is active.
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "lib" / "Kaleidoscope"
target = root / "plugins/Kaleidoscope-Hardware-Keyboardio-Preonic/src/kaleidoscope/device/keyboardio/Preonic.h"
source = target.read_text(encoding="utf-8")
before = (
    "    if (shouldEnterDeepSleep()) {\n"
    "      // Check if we should enter deep sleep\n"
    "      // Only enter deep sleep if no keys are pressed and we're not connected via USB\n"
    "      enterDeepSleep();\n"
    "    }\n"
)
after = (
    "#if 0  // DIAGNOSTIC: disable automatic deep sleep only (increased battery drain)\n"
    + before
    + "#endif  // DIAGNOSTIC: restore this block after isolation test\n"
)
matches = source.count(before)
if matches != 1:
    raise SystemExit(f"Preonic deep-sleep call site changed: expected one match, found {matches}")
target.write_text(source.replace(before, after, 1), encoding="utf-8")
print("Diagnostic: automatic inactivity deep sleep disabled; battery cutoff unchanged")
