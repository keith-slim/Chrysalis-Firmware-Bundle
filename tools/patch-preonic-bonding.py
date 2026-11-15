#!/usr/bin/env python3
"""Preonic nRF52 bond-safety guards and passive security telemetry.

Reject malformed bond records without changing valid pairing/bond behavior.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
security = root / "libraries/Bluefruit52Lib/src/BLESecurity.cpp"
bonding = root / "libraries/Bluefruit52Lib/src/utility/bonding.cpp"

def patch(path, changes):
    source = path.read_text()
    for before, after in changes:
        n = source.count(before)
        if n != 1:
            raise SystemExit(f"{path}: expected exactly one source anchor, got {n}: {before[:100]!r}")
        source = source.replace(before, after, 1)
    source = '#include <stdint.h>\nextern "C" void preonic_bdiag_event(uint16_t, uint16_t, uint16_t);\n' + source
    path.write_text(source)
    print("diagnostic-only", path)

patch(security, [
    (
        '    case BLE_GAP_EVT_SEC_PARAMS_REQUEST:\n    {',
        '    case BLE_GAP_EVT_SEC_PARAMS_REQUEST:\n    {\n'
        '      preonic_bdiag_event(10, conn_hdl, 0);'
    ),
    (
        '      ble_gap_evt_auth_status_t* status = &evt->evt.gap_evt.params.auth_status;',
        '      ble_gap_evt_auth_status_t* status = &evt->evt.gap_evt.params.auth_status;\n'
        '      preonic_bdiag_event(11, status->auth_status, status->bonded);'
    ),
    (
        '      if ( conn->loadBondKey(&bkeys) )\n      {',
        '      if ( conn->loadBondKey(&bkeys) )\n      {\n'
        '        preonic_bdiag_event(12, conn_hdl, 0);'
    ),
    (
        '      } else\n      {\n        VERIFY_STATUS(sd_ble_gap_sec_info_reply(conn_hdl, NULL, NULL, NULL), );',
        '      } else\n      {\n'
        '        preonic_bdiag_event(13, conn_hdl, 0);\n'
        '        VERIFY_STATUS(sd_ble_gap_sec_info_reply(conn_hdl, NULL, NULL, NULL), );'
    ),
    (
        '      const ble_gap_conn_sec_t* conn_sec = &evt->evt.gap_evt.params.conn_sec_update.conn_sec;',
        '      const ble_gap_conn_sec_t* conn_sec = &evt->evt.gap_evt.params.conn_sec_update.conn_sec;\n'
        '      preonic_bdiag_event(14, conn_sec->sec_mode.sm, conn_sec->sec_mode.lv);'
    ),
])
patch(bonding, [
    (
        '  Bluefruit.Connection(conn_hdl)->getPeerName(devname, CFG_MAX_DEVNAME_LEN);',
        '  // Deferred callback may execute after disconnection. Never dereference NULL.\n'
        '  BLEConnection* name_conn = Bluefruit.Connection(conn_hdl);\n'
        '  if (name_conn && name_conn->connected()) {\n'
        '    name_conn->getPeerName(devname, CFG_MAX_DEVNAME_LEN);\n'
        '  }'
    ),
    (
        '        if ( keylen > 0 )\n'
        '        {\n'
        '          file.read((uint8_t*) bkeys, keylen);\n'
        '\n'
        '          ret = true;',
        '        if ( keylen == sizeof(bond_keys_t) )\n'
        '        {\n'
        '          ret = (file.read((uint8_t*) bkeys, sizeof(bond_keys_t)) == sizeof(bond_keys_t));'
    ),
    (
        '          file.read((uint8_t*) bkeys, keylen);\n'
        '          if ( Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info) )',
        '          if (file.read((uint8_t*) bkeys, sizeof(bond_keys_t)) == sizeof(bond_keys_t) &&\n'
        '              Bluefruit.Security.resolveAddress(addr, &bkeys->peer_id.id_info))'
    ),
    (
        'bool bond_load_keys(uint8_t role, ble_gap_addr_t* addr, bond_keys_t* bkeys)\n{\n  bool ret = false;',
        'bool bond_load_keys(uint8_t role, ble_gap_addr_t* addr, bond_keys_t* bkeys)\n{\n  bool ret = false;\n'
        '  uint8_t diagnostic_addr_type = addr->addr_type;'
    ),
    (
        '  return ret;\n}\n\n\n/*------------------------------------------------------------------*/\n/* CCCD',
        '  preonic_bdiag_event(15, diagnostic_addr_type, ret ? 1 : 0);\n'
        '  return ret;\n}\n\n\n/*------------------------------------------------------------------*/\n/* CCCD'
    ),
])
