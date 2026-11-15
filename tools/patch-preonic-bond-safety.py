#!/usr/bin/env python3
"""Preonic-only safety fixes to the official nRF52 bond store.

No BLE callbacks, pairing policy, USB switching, CDC, or diagnostics are changed.
Anchors must match once; an upstream change fails the build instead of silently
applying a partial patch.
"""
from pathlib import Path
import sys

core = Path(sys.argv[1]).resolve()
bonding = core / "libraries/Bluefruit52Lib/src/utility/bonding.cpp"

def apply(source, before, after):
    n = source.count(before)
    if n != 1:
        raise SystemExit(f"{bonding}: expected one source anchor, got {n}: {before[:85]!r}")
    return source.replace(before, after, 1)

source = bonding.read_text()

# A truncated or oversized record must never be loaded into bond_keys_t.
source = apply(source,
    '        if ( keylen > 0 )\n'
    '        {\n'
    '          file.read((uint8_t*) bkeys, keylen);\n'
    '\n'
    '          ret = true;',
    '        if ( keylen == sizeof(bond_keys_t) )\n'
    '        {\n'
    '          ret = (file.read((uint8_t*) bkeys, sizeof(bond_keys_t)) == sizeof(bond_keys_t));'
)
source = apply(source,
    '          file.read((uint8_t*) bkeys, keylen);\n'
    '          if ( Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info) )',
    '          if (file.read((uint8_t*) bkeys, sizeof(bond_keys_t)) == sizeof(bond_keys_t) &&\n'
    '              Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info))'
)

# This deferred callback may run after disconnect; do not dereference NULL.
source = apply(source,
    '  Bluefruit.Connection(conn_hdl)->getPeerName(devname, CFG_MAX_DEVNAME_LEN);',
    '  BLEConnection* name_conn = Bluefruit.Connection(conn_hdl);\n'
    '  if (name_conn && name_conn->connected()) {\n'
    '    name_conn->getPeerName(devname, CFG_MAX_DEVNAME_LEN);\n'
    '  }'
)

# Preserve the previous valid bond until the new complete file is committed.
# LittleFS rename atomically replaces the existing destination.
source = apply(source,
    '  // delete if file already exists\n'
    '  if ( InternalFS.exists(filename) ) InternalFS.remove(filename);\n'
    '\n'
    '  Adafruit_LittleFS_Namespace::File file(filename, FO_WRITE, InternalFS);',
    '  char tmp_filename[BOND_FNAME_LEN + 5];\n'
    '  snprintf(tmp_filename, sizeof(tmp_filename), "%s.tmp", filename);\n'
    '  if (InternalFS.exists(tmp_filename)) InternalFS.remove(tmp_filename);\n'
    '  Adafruit_LittleFS_Namespace::File file(tmp_filename, FO_WRITE, InternalFS);'
)
source = apply(source,
    '  bdata_write(&file, devname, strlen(devname)+1); // save also null char\n'
    '\n'
    '  BOND_LOG("Saved keys for \\"%s\\" to file %s ( %ld bytes )", devname, filename, file.size());\n'
    '\n'
    '  file.close();',
    '  devname[sizeof(devname) - 1] = 0;\n'
    '  bdata_write(&file, devname, strlen(devname)+1); // save also null char\n'
    '  const size_t expected = sizeof(bond_keys_t) + strlen(devname) + 3;\n'
    '  const bool complete = (file.size() == expected);\n'
    '  file.close();\n'
    '  if (!complete || !InternalFS.rename(tmp_filename, filename)) {\n'
    '    InternalFS.remove(tmp_filename);\n'
    '    return;\n'
    '  }'
)
bonding.write_text(source)
print("Applied Preonic bond safety guards without diagnostics:", bonding)
