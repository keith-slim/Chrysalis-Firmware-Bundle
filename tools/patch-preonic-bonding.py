#!/usr/bin/env python3
"""Apply narrowly-scoped bond-store safety fixes to the pinned Preonic nRF52 core.

This patches only the temporary Keyboardio nRF52/Bluefruit52Lib installation
used by the Preonic CI build. Fail closed if the pinned source changes.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
bonding = root / "libraries/Bluefruit52Lib/src/utility/bonding.cpp"
connection = root / "libraries/Bluefruit52Lib/src/BLEConnection.cpp"

def replace_once(source, old, new, path):
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch anchor, got {count}: {old[:100]!r}")
    return source.replace(old, new, 1)

source = bonding.read_text()

start = source.index("static void bond_save_keys_dfr ")
end = source.index("\nbool bond_save_keys ", start)
old = source[start:end]
new = r'''static void bond_save_keys_dfr (uint8_t role, uint16_t conn_hdl, bond_keys_t const * bkeys)
{
  uint8_t const * mac = bkeys->peer_id.id_addr_info.addr;
  char filename[BOND_FNAME_LEN];
  get_fname(filename, role, mac);

  // Never delete the last usable bond before its replacement is committed.
  // LittleFS rename replaces the destination atomically.
  char tempname[BOND_FNAME_LEN + sizeof(".tmp")];
  snprintf(tempname, sizeof(tempname), "%s.tmp", filename);
  InternalFS.remove(tempname);

  Adafruit_LittleFS_Namespace::File file(tempname, FO_WRITE, InternalFS);
  if (!file) {
    BOND_LOG("Failed to open temporary bond file %s", tempname);
    return;
  }

  // Preserve the original on-disk field layout: key length + 80-byte keys,
  // name length + name, then optional CCCD (saved by the following callback).
  const uint8_t keylen = (uint8_t) sizeof(bond_keys_t);
  bool ok = file.write(keylen) == 1;
  ok = file.write((uint8_t const*) bkeys, sizeof(bond_keys_t)) == sizeof(bond_keys_t) && ok;

  char devname[CFG_MAX_DEVNAME_LEN] = { 0 };
  // A deferred save may outlive the BLE connection; do not dereference NULL.
  BLEConnection* conn = Bluefruit.Connection(conn_hdl);
  if (conn && conn->connected()) {
    conn->getPeerName(devname, CFG_MAX_DEVNAME_LEN);
  }
  if (!devname[0]) {
    snprintf(devname, sizeof(devname), "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[5], mac[4], mac[3], mac[2], mac[1], mac[0]);
  }
  const size_t namelen = strlen(devname) + 1;
  ok = file.write((uint8_t) namelen) == 1 && ok;
  ok = file.write((uint8_t const*) devname, namelen) == namelen && ok;
  file.close();

  // Re-open to validate persisted bytes before replacing an existing bond.
  if (ok) {
    Adafruit_LittleFS_Namespace::File verify(tempname, FO_READ, InternalFS);
    bond_keys_t recovered;
    ok = verify && verify.read() == (int) sizeof(bond_keys_t) &&
         verify.read((uint8_t*) &recovered, sizeof(recovered)) == sizeof(recovered) &&
         memcmp(&recovered, bkeys, sizeof(recovered)) == 0;
    verify.close();
  }

  if (ok && InternalFS.rename(tempname, filename)) {
    BOND_LOG("Bond saved atomically to %s", filename);
  } else {
    BOND_LOG("Bond save failed; retaining old bond %s", filename);
    InternalFS.remove(tempname);
  }
}
'''
source=replace_once(source,old,new,bonding)
source=replace_once(source,
'''          file.read((uint8_t*) bkeys, keylen);

          ret = true;
          BOND_LOG("Loaded keys from file %s", filename);''',
'''          if (file.read((uint8_t*) bkeys, keylen) == keylen) {
            ret = true;
            BOND_LOG("Loaded keys from file %s", filename);
          } else {
            BOND_LOG("Short read for bond file %s", filename);
          }''',bonding)
source=replace_once(source,
'''          file.read((uint8_t*) bkeys, keylen);
          if ( Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info) )''',
'''          if (file.read((uint8_t*) bkeys, keylen) == keylen &&
              Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info))''',bonding)
bonding.write_text(source)
print("Patched atomic bond storage and full-length bond reads:",bonding)

# At minimum, propagate deferred callback enqueue failures. Note that the
# callback's return value indicates enqueue success, not disk write completion.
source=connection.read_text()
source=replace_once(source,
'''  bond_save_keys(_role, _conn_hdl, ltkey);
  _bond_id_addr = ltkey->peer_id.id_addr_info;
  _bonded = true;
  return true;''',
'''  // Report a callback queue failure instead of claiming a successful bond.
  if (!bond_save_keys(_role, _conn_hdl, ltkey)) return false;
  _bond_id_addr = ltkey->peer_id.id_addr_info;
  _bonded = true; // In-memory state; disk save is still deferred.
  return true;''',connection)
connection.write_text(source)
print("Patched bond enqueue result handling:",connection)
