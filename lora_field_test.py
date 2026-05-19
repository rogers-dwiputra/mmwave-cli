#!/usr/bin/env python3
"""
lora_field_test.py — LoRa link test dari lokasi jembatan

Usage:
  python3 lora_field_test.py --count 10 --interval 30
  python3 lora_field_test.py --count 5 --interval 60 --port /dev/ttyUSB1
"""

import argparse
import struct
import sys
import time
from datetime import datetime, timedelta

import serial

DEFAULT_PORT   = '/dev/ttyUSB0'
BAUD           = 9600
APPKEY         = '562AD0AB720BA25D830E20164D3CC1B3'
DR             = 5   # SF7
TEST_FPORT     = 9   # port berbeda dari sensor data (fport 8) → tidak masuk Grafana


def _log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}')


def _send_at(ser, cmd, timeout=10.0, expected=None):
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
    return (expected is None), lines


def main(count, interval, port):
    duration_est = timedelta(seconds=(count - 1) * interval + 30)
    print()
    print("=" * 52)
    print("  IoSAR LoRa Field Test — Mizumoto Bridge")
    print(f"  {count} packets · interval {interval}s · SF7 (DR5)")
    print(f"  Estimasi durasi: ~{duration_est}  (fport {TEST_FPORT})")
    print("=" * 52)
    print()

    # ── Open serial ───────────────────────────────────────
    try:
        ser = serial.Serial(port, BAUD, timeout=1)
    except serial.SerialException as exc:
        _log(f'ERROR: Cannot open {port}: {exc}')
        sys.exit(1)

    time.sleep(0.5)
    ser.reset_input_buffer()
    _log(f'Opened {port}')

    try:
        # Wake up
        ok = False
        for retry in range(4):
            ok, _ = _send_at(ser, 'AT', timeout=3, expected='OK')
            if ok:
                break
            _log(f'AT no response — retry {retry+1}/4...')
        if not ok:
            _log('ERROR: Wio-E5 tidak merespons — cek kabel')
            sys.exit(1)

        # Configure
        _send_at(ser, f'AT+KEY=APPKEY,"{APPKEY}"', timeout=3)
        _send_at(ser, 'AT+ADR=ON',            timeout=3, expected='ADR')
        _send_at(ser, f'AT+DR={DR}',           timeout=3, expected='DR')
        _send_at(ser, f'AT+PORT={TEST_FPORT}', timeout=3, expected='PORT')

        # JOIN
        _log('Joining...')
        ok, _ = _send_at(ser, 'AT+JOIN', timeout=30, expected='joined')
        if not ok:
            ok, _ = _send_at(ser, 'AT+JOIN=FORCE', timeout=30, expected='joined')
        if not ok:
            _log('ERROR: JOIN failed')
            sys.exit(1)

        time.sleep(2)
        ser.reset_input_buffer()

        # Send packets
        results = []
        for i in range(1, count + 1):
            print()
            _log(f'─── Packet {i}/{count} ───────────────')

            ts      = int(time.time())
            # Payload: timestamp | seq_num | dr | 0
            # fport=9 → TTN decoder skip, tidak masuk InfluxDB
            payload = struct.pack('>IHHH', ts, i, DR, 0)
            hex_str = payload.hex().upper()
            _log(f'Payload: {hex_str}  (seq={i})')

            ok, resp = _send_at(ser, f'AT+MSGHEX="{hex_str}"',
                                timeout=15, expected='Done')

            rssi, snr = None, None
            for line in resp:
                if 'RXWIN' in line:
                    for part in line.split(','):
                        part = part.strip()
                        if 'RSSI' in part:
                            try: rssi = int(part.split()[-1])
                            except: pass
                        if 'SNR' in part:
                            try: snr = float(part.split()[-1])
                            except: pass

            status = '✅ OK' if ok else '❌ FAIL'
            rssi_s = f'RSSI={rssi} dBm' if rssi is not None else 'RSSI=?'
            snr_s  = f'SNR={snr} dB'   if snr  is not None else 'SNR=?'
            _log(f'{status}  {rssi_s}  {snr_s}')
            results.append({'ok': ok, 'rssi': rssi, 'snr': snr})

            if i < count:
                _log(f'Tunggu {interval}s...')
                time.sleep(interval)

    finally:
        # Kembalikan fport ke 8 (sensor data) sebelum tutup
        _send_at(ser, 'AT+PORT=8', timeout=3, expected='PORT')
        ser.close()
        _log('Serial closed')

    # Summary
    print()
    print("=" * 52)
    print("  SUMMARY")
    print("=" * 52)
    ok_n   = sum(1 for r in results if r['ok'])
    rssi_v = [r['rssi'] for r in results if r['rssi'] is not None]
    snr_v  = [r['snr']  for r in results if r['snr']  is not None]
    print(f"  Berhasil : {ok_n}/{count}  ({100*ok_n//count}%)")
    if rssi_v:
        print(f"  RSSI avg : {sum(rssi_v)/len(rssi_v):.1f} dBm"
              f"  (min {min(rssi_v)}, max {max(rssi_v)})")
    if snr_v:
        print(f"  SNR avg  : {sum(snr_v)/len(snr_v):.1f} dB")
    print()
    print("  Cek RSSI gateway di TTN Console (fport 9):")
    print("  https://imrsl.as1.cloud.thethings.industries/")
    print("=" * 52)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--count',    type=int, default=10,
                        help='Jumlah packet yang dikirim')
    parser.add_argument('--interval', type=int, default=30,
                        help='Interval antar packet (detik)')
    parser.add_argument('--port',     default=DEFAULT_PORT,
                        help='Serial port Wio-E5')
    args = parser.parse_args()
    main(args.count, args.interval, args.port)
