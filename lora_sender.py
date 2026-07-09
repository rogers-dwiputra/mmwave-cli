#!/usr/bin/env python3
"""
LoRa uplink sender for Bridge Health Monitoring
Reads ps_metrics.json → encodes payload → sends via Wio-E5 AT commands

Payload format (variable length, big-endian):

  Header (10 bytes, always present — unchanged from v1):
    Byte 0-3 : Unix timestamp              (uint32, seconds since epoch)
    Byte 4-5 : dominant_frequency_hz × 100 (uint16, 0.01 Hz, max 655.35 Hz)
    Byte 6-7 : displacement_rms_mm × 1000  (uint16, 0.001 mm, max 65.535 mm)
    Byte 8-9 : max_deflection_mm × 1000    (uint16, 0.001 mm, max 65.535 mm)

  Per-PS section (present when ps_details available in ps_metrics.json):
    Byte 10   : N_PS  (uint8, number of PS points, 0 = no per-PS data)
    Byte 11+  : Per-PS data, 4 bytes per PS point:
                  uint16 : ps_i dominant_frequency_hz × 100  (0 = no peak)
                  uint16 : ps_i disp_rms_mm × 1000

  Example: 5 PS points → total 11 + 5×4 = 31 bytes (well within SF7 AS923 limit)

Decoder (gateway side):
  ts       = struct.unpack('>I', byte[0:4])[0]   # Unix timestamp
  freq_hz  = struct.unpack('>H', byte[4:6])[0] / 100.0
  rms_mm   = struct.unpack('>H', byte[6:8])[0] / 1000.0
  max_mm   = struct.unpack('>H', byte[8:10])[0] / 1000.0
  n_ps     = byte[10] if len(byte) > 10 else 0
  for i in range(n_ps):
      freq_i = struct.unpack('>H', byte[11+4*i:13+4*i])[0] / 100.0
      rms_i  = struct.unpack('>H', byte[13+4*i:15+4*i])[0] / 1000.0
"""

import argparse
import json
import os
import struct
import time
from datetime import datetime

import serial

# ─────────────────────────────────────────────
# Default LoRa configuration  (Wio-E5 DevKit)
# ─────────────────────────────────────────────
DEFAULT_PORT   = '/dev/ttyUSB0'
DEFAULT_BAUD   = 9600
DEFAULT_APPKEY = '562AD0AB720BA25D830E20164D3CC1B3'

# ADR (Adaptive Data Rate) — allow TTN to optimize SF automatically after ~5 packets.
# Uses AT+ADR=1 (numeric form, reliable across all Wio-E5 firmware versions).
DEFAULT_ADR    = True

# Starting Data Rate for Japan 920 MHz (AS923):
#   DR0=SF12, DR1=SF11, DR2=SF10 (firmware default), DR3=SF9, DR4=SF8, DR5=SF7
#   DR5 (SF7) → airtime 46ms vs 371ms for SF10 — use for distances <500m.
#   Drop to DR4 (SF8) if link margin is insufficient in the field.
#   Setting is saved to Wio-E5 flash; sent each cycle to ensure consistent state.
DEFAULT_DR     = 5  # SF7, BW125kHz

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
HOME_DIR   = os.path.expanduser('~')
EDGE_DIR   = os.path.join(HOME_DIR, 'IoSAR-EdgeProcessing')
RESULT_DIR = os.path.join(EDGE_DIR, 'python-result')


# ═════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════

def _log(msg: str) -> None:
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] [LoRa] {msg}')


def _send_at(ser: serial.Serial, cmd: str,
             timeout: float = 5.0,
             expected: str = None) -> tuple:
    """
    Send one AT command, collect response lines until:
      - expected string is found in a line, or
      - '+ERR' / 'ERROR' appears, or
      - timeout expires.

    Returns (success: bool, lines: list[str]).
    """
    _log(f'→ {cmd}')
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode())
    ser.flush()

    lines    = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        if ser.in_waiting:
            raw  = ser.readline()
            line = raw.decode(errors='replace').strip()
            if not line:
                continue
            _log(f'← {line}')
            lines.append(line)

            if expected and expected.lower() in line.lower():
                return True, lines
            if '+ERR' in line or 'ERROR' in line.upper():
                return False, lines
        else:
            time.sleep(0.05)

    # Timeout — treat as success if no expected string was required
    success = (expected is None)
    return success, lines


# ═════════════════════════════════════════════
# Payload encoding
# ═════════════════════════════════════════════

def encode_payload(metrics: dict) -> str:
    """
    Pack header + optional per-PS data into big-endian payload.
    Timestamp comes from metrics['timestamp'] (ISO string from capture).
    Returns uppercase hex string (no '0x' prefix).
    """
    # ── Timestamp ────────────────────────────────────────────────────
    ts_raw = metrics.get('timestamp')
    if ts_raw:
        try:
            from datetime import timezone
            dt = datetime.fromisoformat(ts_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts_unix = int(dt.timestamp())
        except Exception:
            ts_unix = int(time.time())
    else:
        ts_unix = int(time.time())

    # ── Overall values (header) ───────────────────────────────────────
    freq = float(metrics.get('dominant_frequency_hz')
                 or metrics.get('freq_mode_1_hz')
                 or metrics.get('natural_frequency_hz') or 0.0)
    rms_mm = metrics.get('displacement_rms_mm')
    if rms_mm is None:
        rms_um = float(metrics.get('displacement_rms_um') or 0.0)
        rms_mm = rms_um / 1000.0
    else:
        rms_mm = float(rms_mm)
    mdef = float(metrics.get('max_deflection_mm') or 0.0)

    freq_int = min(int(round(freq   * 100)),  65535)
    rms_int  = min(int(round(rms_mm * 1000)), 65535)
    def_int  = min(int(round(mdef   * 1000)), 65535)

    header = struct.pack('>IHHH', ts_unix, freq_int, rms_int, def_int)

    # ── Per-PS section ────────────────────────────────────────────────
    ps_details = metrics.get('ps_details', [])
    n_ps = min(len(ps_details), 15)   # cap at 15 PS (max payload 11+15×4=71 bytes)

    ps_bytes = b''
    ps_log   = []
    for i, ps in enumerate(ps_details[:n_ps]):
        ps_freq = float(ps.get('dominant_frequency_hz') or 0.0)
        ps_rms  = float(ps.get('disp_rms_mm') or 0.0)
        pf_int  = min(int(round(ps_freq * 100)),  65535)
        pr_int  = min(int(round(ps_rms  * 1000)), 65535)
        ps_bytes += struct.pack('>HH', pf_int, pr_int)
        ps_log.append(f'PS{i}:{ps_freq:.2f}Hz/{ps_rms*1e3:.1f}μm')

    payload = header + struct.pack('>B', n_ps) + ps_bytes
    hex_str = payload.hex().upper()

    ts_fmt = datetime.fromtimestamp(ts_unix).strftime('%Y-%m-%d %H:%M:%S')
    _log(f'Encode → ts={ts_fmt}  freq={freq:.2f} Hz  '
         f'rms={rms_mm*1e3:.3f} μm  max={mdef*1e3:.3f} μm  n_ps={n_ps}')
    if ps_log:
        _log(f'Per-PS → {" | ".join(ps_log)}')
    _log(f'Payload hex ({len(payload)} bytes): {hex_str}')
    return hex_str


# ═════════════════════════════════════════════
# Find latest metrics
# ═════════════════════════════════════════════

def find_latest_metrics() -> str | None:
    """Return path to the most recently modified ps_metrics.json."""
    if not os.path.isdir(RESULT_DIR):
        _log(f'Result dir not found: {RESULT_DIR}')
        return None

    candidates = []
    for name in os.listdir(RESULT_DIR):
        path = os.path.join(RESULT_DIR, name, 'ps_metrics.json')
        if os.path.isfile(path):
            candidates.append((os.path.getmtime(path), path))

    if not candidates:
        _log('No ps_metrics.json found in python-result/')
        return None

    latest = sorted(candidates)[-1][1]
    return latest


# ═════════════════════════════════════════════
# Session + confirmed uplink  (used by lora_queue drain)
# ═════════════════════════════════════════════

def open_session(port: str = DEFAULT_PORT,
                 baud: int = DEFAULT_BAUD,
                 appkey: str = DEFAULT_APPKEY,
                 dr: int = DEFAULT_DR,
                 adr: bool = DEFAULT_ADR,
                 ser_factory=None):
    """
    Open the Wio-E5 serial port, configure (APPKEY/ADR/DR) and join OTAA.
    Returns a ready serial handle for repeated sends, or None on failure.
    Caller is responsible for closing the returned handle.
    `ser_factory` allows tests to inject a fake serial object.
    """
    try:
        ser = ser_factory() if ser_factory else serial.Serial(port, baud, timeout=1)
    except serial.SerialException as exc:
        _log(f'ERROR: Cannot open {port}: {exc}')
        return None

    time.sleep(0.5)
    ser.reset_input_buffer()
    _log(f'Opened {port} @ {baud} baud')

    ok = False
    for _retry in range(4):
        ok, _ = _send_at(ser, 'AT', timeout=3, expected='OK')
        if ok:
            break
        _log(f'AT no response — retry {_retry + 1}/4...')
    if not ok:
        _log('ERROR: No response from Wio-E5 — check cable and port')
        ser.close()
        return None

    _send_at(ser, f'AT+KEY=APPKEY,"{appkey}"', timeout=3)
    if adr:
        ok_adr, _ = _send_at(ser, 'AT+ADR=ON', timeout=3, expected='ADR')
        if not ok_adr:
            _log('WARNING: AT+ADR=ON not confirmed — continuing...')
    ok_dr, dr_resp = _send_at(ser, f'AT+DR={dr}', timeout=3, expected='DR')
    if ok_dr:
        dr_line = next((l for l in dr_resp if '+DR:' in l), '')
        _log(f'DR set: {dr_line}')
    else:
        _log(f'WARNING: AT+DR={dr} not confirmed — continuing...')

    _log('Checking join status...')
    ok, _ = _send_at(ser, 'AT+JOIN', timeout=30, expected='joined')
    if not ok:
        _log('WARNING: Join may have failed — attempting force rejoin...')
        ok, _ = _send_at(ser, 'AT+JOIN=FORCE', timeout=30, expected='joined')
        if not ok:
            _log('ERROR: Join failed')
            ser.close()
            return None

    # Let all join response lines finish before the first send
    # (avoids "+JOIN: Done" leaking into the next response buffer)
    time.sleep(2)
    ser.reset_input_buffer()
    return ser


def send_payload_confirmed(ser, hex_payload: str, timeout: float = 30.0) -> bool:
    """
    Confirmed uplink via AT+CMSGHEX. True only when the network ACK arrives.
    Without ACK (gateway down, out of range) the Wio-E5 prints '+CMSGHEX: Done'
    but never 'ACK Received' — that is a delivery failure.
    """
    ok, _ = _send_at(ser, f'AT+CMSGHEX="{hex_payload}"',
                     timeout=timeout, expected='ACK Received')
    if ok:
        _log(f'✓ Confirmed uplink delivered (ACK) — {hex_payload}')
    else:
        _log('✗ No ACK received — delivery failed, message stays queued')
    return ok


# ═════════════════════════════════════════════
# Main send function
# ═════════════════════════════════════════════

def send_lora(metrics_path: str = None,
              port: str   = DEFAULT_PORT,
              baud: int   = DEFAULT_BAUD,
              appkey: str = DEFAULT_APPKEY,
              dr: int     = DEFAULT_DR,
              adr: bool   = DEFAULT_ADR) -> bool:
    """
    Full LoRa uplink sequence:
      1. Test AT
      2. Set APPKEY
      3. Set ADR=1 (if adr=True) and starting Data Rate
      4. Join (OTAA) — AT+JOIN handles "already joined" transparently
      5. Send MSGHEX payload
    Returns True on success.
    """
    # ── Load metrics ──────────────────────────────────────────────────
    if metrics_path is None:
        metrics_path = find_latest_metrics()
    if metrics_path is None:
        _log('ERROR: No metrics available to send')
        return False

    with open(metrics_path) as fh:
        metrics = json.load(fh)

    capture = metrics.get('capture', os.path.basename(os.path.dirname(metrics_path)))
    _log(f'Metrics loaded: {capture}')

    hex_payload = encode_payload(metrics)

    # ── Open + join session ───────────────────────────────────────────
    ser = open_session(port=port, baud=baud, appkey=appkey, dr=dr, adr=adr)
    if ser is None:
        return False

    try:
        # ── Send payload (unconfirmed, legacy path) ────────────────────
        _log('Sending payload...')
        ok, resp = _send_at(ser, f'AT+MSGHEX="{hex_payload}"',
                            timeout=15, expected='Done')
        if ok:
            _log(f'✓ Uplink sent successfully — payload: {hex_payload}')
        else:
            _log('WARNING: No "Done" received — packet may not have been sent')
        return ok
    finally:
        ser.close()
        _log(f'Serial port {port} closed')


# ═════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Send PS monitoring metrics via LoRaWAN (Wio-E5)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--metrics', default=None,
                        help='Path to ps_metrics.json (default: latest in python-result/)')
    parser.add_argument('--port',   default=DEFAULT_PORT,
                        help='Serial port of Wio-E5')
    parser.add_argument('--baud',   default=DEFAULT_BAUD, type=int,
                        help='Serial baud rate')
    parser.add_argument('--appkey', default=DEFAULT_APPKEY,
                        help='LoRaWAN APPKEY (32 hex chars)')
    parser.add_argument('--dr', type=int, default=DEFAULT_DR,
                        choices=range(0, 6), metavar='DR',
                        help='Starting Data Rate: DR0=SF12 … DR5=SF7 (default: %(default)s=SF7)')
    parser.add_argument('--no-adr', action='store_true',
                        help='Disable ADR (Adaptive Data Rate) — not recommended')
    args = parser.parse_args()

    success = send_lora(args.metrics, args.port, args.baud, args.appkey,
                        dr=args.dr,
                        adr=not args.no_adr)
    raise SystemExit(0 if success else 1)
