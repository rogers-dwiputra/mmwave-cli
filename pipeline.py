#!/usr/bin/env python3
"""
Automated MIMO Radar Pipeline
Continuously: capture → transfer data from TDA → edge processing → repeat

Usage:
    python3 pipeline.py
    python3 pipeline.py --duration 10 --interval 5
    python3 pipeline.py --duration 60 --tda-ip 192.168.33.180

Press Ctrl+C to stop gracefully after the current cycle completes.
"""

import argparse
import glob
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

# ─────────────────────────────────────────────
# Paths  (resolved relative to this script)
# ─────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
HOME_DIR       = os.path.expanduser('~')
EDGE_DIR       = os.path.join(HOME_DIR, 'IoSAR-EdgeProcessing')
POSTPROC_DIR   = os.path.join(EDGE_DIR, 'PostProc')
JSON_FILES_DIR = os.path.join(SCRIPT_DIR, 'mmwave_json_files')
TDA_IP_DEFAULT = '192.168.33.180'

# ─────────────────────────────────────────────
# Graceful shutdown
# ─────────────────────────────────────────────
shutdown_flag = False

def _handle_signal(sig, frame):
    global shutdown_flag
    print('\n\n[PIPELINE] Interrupt received — stopping after current cycle...')
    shutdown_flag = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _banner(title: str) -> None:
    print(f'\n{"="*60}')
    print(f'  {title}')
    print(f'{"="*60}')

def _step(msg: str) -> None:
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}')


# ─────────────────────────────────────────────
# Step 1 — Capture
# ─────────────────────────────────────────────

def run_capture(duration: float, tda_ip: str, label: str) -> str | None:
    """
    Execute one capture cycle via mimo.py.
    Returns the capture directory name (e.g. 'RPI_python_sine_2hz_1mm_10s_20260510_144105'),
    or None on failure.
    """
    _banner(f'STEP 1 — Radar Capture  ({duration}s)')

    # Remember existing JSON files so we can detect the new one afterwards.
    before = set(glob.glob(os.path.join(JSON_FILES_DIR, '*.mmwave.json')))

    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, 'mimo.py'),
        '--duration', str(duration),
        '--tda-ip',   tda_ip,
        '--num-loops', '1',
        '--directory', label,
    ]
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f'[PIPELINE] ERROR: mimo.py exited with code {result.returncode}')
        return None

    # Identify the newly created .mmwave.json file.
    after     = set(glob.glob(os.path.join(JSON_FILES_DIR, '*.mmwave.json')))
    new_files = after - before

    if not new_files:
        print('[PIPELINE] ERROR: No new .mmwave.json generated — capture likely failed')
        return None

    new_json = list(new_files)[0]

    stem = os.path.basename(new_json)
    if stem.endswith('.mmwave.json'):
        capture_dir = stem[: -len('.mmwave.json')]
        _step(f'Capture directory: {capture_dir}')
        return capture_dir

    return None


# ─────────────────────────────────────────────
# Step 2 — Transfer
# ─────────────────────────────────────────────

def transfer_data(capture_dir: str, tda_ip: str) -> bool:
    """
    SCP capture data from TDA board → PostProc,
    fix permissions, and move the .mmwave.json into the capture folder.
    Returns True on success.
    """
    _banner(f'STEP 2 — Transfer Data  ({capture_dir})')

    remote_src = f'root@{tda_ip}:/mnt/ssd/{capture_dir}'
    os.makedirs(POSTPROC_DIR, exist_ok=True)

    _step(f'SCP  {remote_src}  →  {POSTPROC_DIR}/')
    scp_cmd = [
        'scp',
        '-O',
        '-oHostKeyAlgorithms=+ssh-rsa',
        '-oPubkeyAcceptedAlgorithms=+ssh-rsa',
        '-oStrictHostKeyChecking=no',
        '-r',
        remote_src,
        POSTPROC_DIR + '/',
    ]
    result = subprocess.run(scp_cmd)
    if result.returncode != 0:
        print(f'[PIPELINE] ERROR: SCP transfer failed (exit {result.returncode})')
        return False

    # Fix ownership/permissions on files copied as root.
    _step('Fixing permissions...')
    subprocess.run(['chmod', '-R', 'u+rwx', POSTPROC_DIR], check=False)

    # Move the .mmwave.json config file into the capture directory.
    json_src     = os.path.join(JSON_FILES_DIR, f'{capture_dir}.mmwave.json')
    capture_path = os.path.join(POSTPROC_DIR, capture_dir)
    if os.path.isfile(json_src):
        os.makedirs(capture_path, exist_ok=True)
        dst = os.path.join(capture_path, f'{capture_dir}.mmwave.json')
        shutil.move(json_src, dst)
        _step(f'Moved config JSON → {dst}')
    else:
        print(f'[PIPELINE] WARNING: JSON config not found: {json_src}')

    return True


# ─────────────────────────────────────────────
# Step 3 — Edge Processing (SLC + Range Profile)
# ─────────────────────────────────────────────

_mimo_processing_mod = None

def _load_mimo_processing():
    global _mimo_processing_mod
    if _mimo_processing_mod is not None:
        return _mimo_processing_mod
    mod_path = os.path.join(EDGE_DIR, 'mimo_processing.py')
    if not os.path.isfile(mod_path):
        raise FileNotFoundError(f'mimo_processing.py not found at {mod_path}')
    spec = importlib.util.spec_from_file_location('mimo_processing', mod_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mimo_processing_mod = mod
    return mod


def run_processing(capture_dir: str) -> bool:
    """Generate SLC.png and range-profile.png for a single capture directory."""
    _banner(f'STEP 3 — Edge Processing  ({capture_dir})')

    data_folder = os.path.join(POSTPROC_DIR, capture_dir)
    if not os.path.isdir(data_folder):
        print(f'[PIPELINE] ERROR: Capture directory not found: {data_folder}')
        return False

    try:
        mod = _load_mimo_processing()
        mod.process_capture(data_folder)
        return True
    except Exception as exc:
        import traceback
        print(f'[PIPELINE] ERROR during processing: {exc}')
        traceback.print_exc()
        return False


# ─────────────────────────────────────────────
# Step 4 — PS Monitoring (Natural Frequency)
# ─────────────────────────────────────────────


_ps_monitoring_mod = None

def _load_ps_monitoring():
    global _ps_monitoring_mod
    if _ps_monitoring_mod is not None:
        return _ps_monitoring_mod
    mod_path = os.path.join(EDGE_DIR, 'ps_monitoring.py')
    if not os.path.isfile(mod_path):
        raise FileNotFoundError(f'ps_monitoring.py not found at {mod_path}')
    spec = importlib.util.spec_from_file_location('ps_monitoring', mod_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _ps_monitoring_mod = mod
    return mod


def run_ps_monitoring(capture_dir: str, ps_map_file: str,
                      ps_file: str = None) -> dict:
    """Run PS-based structural health monitoring for one capture directory."""
    _banner(f'STEP 4 — PS Monitoring  ({capture_dir})')

    data_folder = os.path.join(POSTPROC_DIR, capture_dir)
    if not os.path.isdir(data_folder):
        print(f'[PIPELINE] ERROR: Capture directory not found: {data_folder}')
        return {}

    try:
        mod = _load_ps_monitoring()
        return mod.run_ps_monitoring(data_folder, ps_map_file, ps_file)
    except Exception as exc:
        import traceback
        print(f'[PIPELINE] ERROR during PS monitoring: {exc}')
        traceback.print_exc()
        return {}


# ─────────────────────────────────────────────
# Step 5 — LoRa uplink (Wio-E5)
# ─────────────────────────────────────────────

def run_lora_send(capture_dir: str,
                  port: str, appkey: str) -> bool:
    """Send ps_metrics.json for this capture via LoRaWAN."""
    _banner(f'STEP 5 — LoRa Uplink  ({capture_dir})')

    metrics_path = os.path.join(
        EDGE_DIR, 'python-result', capture_dir, 'ps_metrics.json'
    )
    if not os.path.isfile(metrics_path):
        print(f'[PIPELINE] ERROR: ps_metrics.json not found: {metrics_path}')
        return False

    try:
        # Import lora_sender from the same directory as pipeline.py
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            'lora_sender',
            os.path.join(SCRIPT_DIR, 'lora_sender.py'),
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod.send_lora(metrics_path=metrics_path,
                              port=port, appkey=appkey)
    except Exception as exc:
        import traceback
        print(f'[PIPELINE] ERROR during LoRa send: {exc}')
        traceback.print_exc()
        return False


# ─────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Automated MIMO Radar Capture & Processing Pipeline',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('-t', '--duration',  type=float, default=10.0,
                        help='Radar capture duration in seconds')
    parser.add_argument('--label',           type=str,   default='RPI_python',
                        help='Experiment label used as capture directory prefix '
                             '(e.g. RPI_python_sine_2hz_1mm_10s). '
                             'Timestamp is appended automatically by mimo.py.')
    parser.add_argument('--tda-ip',          type=str,   default=TDA_IP_DEFAULT,
                        help='TDA board IP address')
    parser.add_argument('-i', '--interval',  type=float, default=0.0,
                        help='Wait time between cycles in seconds (0 = no delay)')
    parser.add_argument('--debug',           action='store_true',
                        help='Debug mode: also generate SLC image and range-profile plots '
                             'after transfer. Without this flag, only PS metrics are computed '
                             '(faster, recommended for long monitoring sessions).')
    parser.add_argument('--skip-transfer',   action='store_true',
                        help='Skip SCP transfer step (useful for testing processing only)')
    parser.add_argument('--skip-ps',         action='store_true',
                        help='Skip PS monitoring step')
    parser.add_argument('--ps-file',         type=str, default=None,
                        help='Path to manually-selected PS JSON (from select_ps_manual.m). '
                             'Skips ADI computation — use after first manual PS selection.')
    parser.add_argument('--reset-ps',        action='store_true',
                        help='Delete PS map so it is recomputed on the next cycle (ignored when --ps-file is set)')
    parser.add_argument('--skip-lora',       action='store_true',
                        help='Skip LoRa uplink step')
    parser.add_argument('--lora-port',       type=str,
                        default='/dev/ttyUSB0',
                        help='Serial port of Wio-E5 LoRa module')
    parser.add_argument('--lora-appkey',     type=str,
                        default='562AD0AB720BA25D830E20164D3CC1B3',
                        help='LoRaWAN APPKEY (32 hex chars)')
    args = parser.parse_args()

    # PS map lives alongside mimo_processing.py in IoSAR-EdgeProcessing/
    ps_map_file = os.path.join(EDGE_DIR, 'ps_map.json')
    if args.reset_ps and args.ps_file is None and os.path.isfile(ps_map_file):
        os.remove(ps_map_file)
        print(f'[PIPELINE] Deleted PS map: {ps_map_file}')

    print('╔══════════════════════════════════════════════════════════╗')
    print('║        AUTOMATED MIMO RADAR PIPELINE — IMRSL            ║')
    print('╚══════════════════════════════════════════════════════════╝')
    print(f'  Capture duration : {args.duration}s')
    print(f'  Capture label    : {args.label}')
    print(f'  TDA IP address   : {args.tda_ip}')
    print(f'  Cycle interval   : {args.interval}s')
    print(f'  PostProc dir     : {POSTPROC_DIR}')
    print(f'  Results dir      : {os.path.join(EDGE_DIR, "python-result")}')
    print(f'  PS source        : {args.ps_file if args.ps_file else ps_map_file + " (auto/ADI)"}')
    print(f'  Debug mode       : {"ON (SLC + range-profile enabled)" if args.debug else "OFF (PS metrics only)"}')
    print(f'  LoRa port        : {"disabled (--skip-lora)" if args.skip_lora else args.lora_port}')
    print(f'  Press Ctrl+C to stop after the current cycle.')

    os.makedirs(POSTPROC_DIR,   exist_ok=True)
    os.makedirs(JSON_FILES_DIR, exist_ok=True)

    cycle = 0
    while not shutdown_flag:
        cycle += 1
        t_start = time.time()

        print(f'\n{"#"*60}')
        print(f'# CYCLE {cycle:4d}   [{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]')
        print(f'{"#"*60}')

        # ── 1. Capture ──────────────────────────────────────────────
        capture_dir = run_capture(args.duration, args.tda_ip, args.label)
        if capture_dir is None:
            print('[PIPELINE] Capture failed — retrying in 10s...')
            time.sleep(10)
            continue

        if shutdown_flag:
            break

        # ── 2. Transfer ─────────────────────────────────────────────
        if not args.skip_transfer:
            ok = transfer_data(capture_dir, args.tda_ip)
            if not ok:
                print('[PIPELINE] Transfer failed — skipping processing for this cycle')
                if args.interval > 0:
                    time.sleep(args.interval)
                continue
        else:
            _step('Transfer skipped (--skip-transfer)')

        if shutdown_flag:
            break

        # ── 3. SLC + Range Profile (debug mode only) ────────────────
        if args.debug:
            run_processing(capture_dir)
        else:
            _step('SLC/range-profile skipped (add --debug to enable)')

        if shutdown_flag:
            break

        # ── 4. PS Monitoring ────────────────────────────────────────
        if not args.skip_ps:
            run_ps_monitoring(capture_dir, ps_map_file, args.ps_file)
        else:
            _step('PS monitoring skipped (--skip-ps)')

        if shutdown_flag:
            break

        # ── 5. LoRa uplink ──────────────────────────────────────────
        if not args.skip_lora:
            run_lora_send(capture_dir, args.lora_port, args.lora_appkey)
        else:
            _step('LoRa uplink skipped (--skip-lora)')

        elapsed = time.time() - t_start
        _banner(f'Cycle {cycle} done in {elapsed:.1f}s')

        if shutdown_flag:
            break

        if args.interval > 0:
            _step(f'Waiting {args.interval}s before next cycle...')
            time.sleep(args.interval)

    print('\n[PIPELINE] Pipeline stopped cleanly.')


if __name__ == '__main__':
    main()
