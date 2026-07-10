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
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

import tda_recovery

# ─────────────────────────────────────────────
# Paths  (resolved relative to this script)
# ─────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
HOME_DIR       = os.path.expanduser('~')
EDGE_DIR       = os.path.join(HOME_DIR, 'IoSAR-EdgeProcessing')
# SSD write causes RPi undervoltage → I/O errors for large .bin files.
# Keep raw captures on SD card (safe); SSD used only for manual archiving.
# POSTPROC_DIR = '/media/imrsl/Extreme SSD/PostProc'  # SSD — avoid: undervoltage
POSTPROC_DIR   = os.path.join(EDGE_DIR, 'PostProc')   # SD card (118 GB, ~180 captures)
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

def _ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _banner(title: str) -> None:
    ts = _ts()
    print(f'\n{"="*60}')
    print(f'  {title}')
    print(f'  {ts}')
    print(f'{"="*60}')

def _step(msg: str) -> None:
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}', flush=True)

def _step_start(name: str) -> float:
    """Log step start and return start time."""
    t = time.time()
    print(f'[{datetime.now().strftime("%H:%M:%S")}] ▶ {name} started', flush=True)
    return t

def _step_done(name: str, t_start: float) -> float:
    """Log step end with elapsed time. Returns elapsed seconds."""
    elapsed = time.time() - t_start
    print(f'[{datetime.now().strftime("%H:%M:%S")}] ✓ {name} done  ({elapsed:.1f}s)', flush=True)
    return elapsed


def _free_gb(path: str) -> float:
    """Return free disk space in GB for the filesystem containing `path`."""
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


def _auto_cleanup(postproc_dir: str, label: str, min_free_gb: float) -> None:
    """
    Delete oldest capture directories whose name starts with `label`
    under `postproc_dir` until free disk space >= min_free_gb.
    Directories are sorted by name (which contains a timestamp suffix,
    so alphabetical order = chronological order).
    Skips deletion if fewer than 2 matching directories exist (keep at
    least the most recent one for reference).
    """
    free = _free_gb(postproc_dir)
    if free >= min_free_gb:
        return

    # Collect matching dirs sorted oldest-first (name order = time order)
    candidates = sorted([
        os.path.join(postproc_dir, d)
        for d in os.listdir(postproc_dir)
        if d.startswith(label) and os.path.isdir(os.path.join(postproc_dir, d))
    ])

    if len(candidates) < 2:
        print(f'[CLEANUP] Only {len(candidates)} matching dir(s) — skipping auto-delete '
              f'(free: {free:.1f} GB < {min_free_gb:.1f} GB threshold)')
        return

    print(f'[CLEANUP] Free space {free:.1f} GB < {min_free_gb:.1f} GB — '
          f'auto-deleting oldest captures with prefix "{label}"...')

    # Keep the newest one; delete oldest until threshold met
    for path in candidates[:-1]:
        free = _free_gb(postproc_dir)
        if free >= min_free_gb:
            break
        size_gb = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, files in os.walk(path)
            for f in files
        ) / 1e9
        shutil.rmtree(path, ignore_errors=True)
        print(f'[CLEANUP]  Deleted {os.path.basename(path)}  ({size_gb:.2f} GB)  '
              f'→ free now {_free_gb(postproc_dir):.1f} GB')

    free = _free_gb(postproc_dir)
    if free < min_free_gb:
        print(f'[CLEANUP] WARNING: still only {free:.1f} GB free after cleanup — '
              f'consider manual cleanup of {postproc_dir}')
    else:
        print(f'[CLEANUP] Done — free space now {free:.1f} GB')


def _do_idle_sleep(seconds: float, use_suspend: bool) -> None:
    """
    Sleep for `seconds` to fill a fixed cycle period.
    If use_suspend=True, calls sudo rtcwake -m mem to suspend the RPi to RAM
    (saves ~95% power vs idle). Falls back to time.sleep on failure.
    After rtcwake resumes, waits 10s for the Ethernet link to recover.
    """
    if seconds <= 0:
        return
    wake_at = datetime.now().strftime('%H:%M:%S')
    import math
    resume_ts = datetime.fromtimestamp(time.time() + seconds).strftime('%H:%M:%S')

    if use_suspend:
        # Detect best available suspend state: mem > standby > freeze
        try:
            avail = open('/sys/power/state').read().split()
        except OSError:
            avail = []
        state = next((s for s in ('mem', 'standby', 'freeze') if s in avail), None)

        if state is None:
            print('[PIPELINE] WARNING: no suspend states available in /sys/power/state '
                  '— falling back to time.sleep (RPi 5 may need kernel support for suspend)')
        else:
            secs_int = max(30, int(math.ceil(seconds)))
            _step(f'Suspending ({state}) for {secs_int}s  (resume ~{resume_ts}) — power-save mode')
            result = subprocess.run(
                ['sudo', '/usr/sbin/rtcwake', '-m', state, '-s', str(secs_int)],
                timeout=secs_int + 60,
            )
            if result.returncode == 0:
                _step('Resumed from suspend — waiting 10s for network...')
                time.sleep(10)
                return
            print(f'[PIPELINE] WARNING: rtcwake failed (exit {result.returncode}) — falling back to time.sleep')

    _step(f'Sleeping {seconds:.0f}s until next cycle  (resume ~{resume_ts})')
    # Break into 10s chunks so Ctrl+C is responsive
    remaining = seconds
    while remaining > 0 and not shutdown_flag:
        time.sleep(min(10, remaining))
        remaining -= 10


def _ladder_sleep(seconds: float) -> None:
    """Interruptible sleep for recovery-ladder waits: returns early once the
    shutdown flag is set (plain time.sleep resumes after SIGINT, PEP 475)."""
    end = time.time() + seconds
    while not shutdown_flag and time.time() < end:
        time.sleep(min(1.0, end - time.time()))


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
    # chown requires sudo (only root can change file ownership).
    _step('Fixing permissions...')
    current_user = os.environ.get('USER', 'imrsl')
    capture_path_fix = os.path.join(POSTPROC_DIR, capture_dir)
    subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', capture_path_fix], check=False)
    subprocess.run(['chmod', '-R', 'u+rwX', capture_path_fix], check=False)

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

    # Delete raw data from TDA SSD after successful transfer to free space.
    # Raw .bin files are now safely stored on RPi (PostProc dir).
    _step(f'Deleting from TDA SSD: /mnt/ssd/{capture_dir}')
    ssh_cmd = [
        'ssh',
        '-oHostKeyAlgorithms=+ssh-rsa',
        '-oPubkeyAcceptedAlgorithms=+ssh-rsa',
        '-oStrictHostKeyChecking=no',
        f'root@{tda_ip}',
        f'rm -rf /mnt/ssd/{capture_dir}',
    ]
    del_result = subprocess.run(ssh_cmd)
    if del_result.returncode == 0:
        _step(f'TDA SSD cleaned — /mnt/ssd/{capture_dir} deleted')
    else:
        print(f'[PIPELINE] WARNING: TDA delete failed (exit {del_result.returncode}) '
              f'— manual cleanup may be needed: rm -rf /mnt/ssd/{capture_dir}')

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
# Step 4 — PS Monitoring (Dominant Frequency)
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
# Step 5 — LoRa uplink via store-and-forward queue (Wio-E5)
# ─────────────────────────────────────────────

def run_lora_step(capture_dir: str, port: str, appkey: str,
                  skip_send: bool = False) -> bool:
    """Enqueue this cycle's metrics, then drain the spool (oldest-first,
    confirmed uplinks). Enqueue always happens — even with --skip-lora —
    so no data is ever lost. Returns True when the spool is empty afterwards."""
    import lora_queue
    import lora_sender

    _banner(f'STEP 5 — LoRa Uplink  ({capture_dir})')

    metrics_path = os.path.join(EDGE_DIR, 'python-result', capture_dir, 'ps_metrics.json')
    if os.path.isfile(metrics_path):
        with open(metrics_path) as fh:
            metrics = json.load(fh)
        spooled = lora_queue.enqueue(metrics)
        _step(f'Queued → {os.path.basename(spooled)}')
    else:
        print(f'[PIPELINE] WARNING: ps_metrics.json not found: {metrics_path} — nothing to queue')

    pending = lora_queue.list_pending()
    if skip_send:
        _step(f'LoRa send skipped (--skip-lora) — {len(pending)} message(s) queued')
        return True
    if not pending:
        _step('LoRa queue empty — nothing to send')
        return True

    ses = lora_sender.open_session(port=port, appkey=appkey)
    if ses is None:
        _step(f'LoRa link unavailable — {len(pending)} message(s) remain queued')
        return False
    try:
        sent, remaining = lora_queue.drain(
            lambda hex_payload: lora_sender.send_payload_confirmed(ses, hex_payload))
    finally:
        ses.close()
    _step(f'LoRa drain: {sent} sent, {remaining} still pending')
    return remaining == 0


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
                        help='Skip LoRa sending (metrics are still queued in ~/lora_queue for later drain)')
    parser.add_argument('--lora-port',       type=str,
                        default='/dev/ttyUSB0',
                        help='Serial port of Wio-E5 LoRa module')
    parser.add_argument('--lora-appkey',     type=str,
                        default='562AD0AB720BA25D830E20164D3CC1B3',
                        help='LoRaWAN APPKEY (32 hex chars)')
    parser.add_argument('--cycle-period',   type=float, default=0.0,
                        help='Target total time per cycle in seconds (e.g. 900 for 15-min cadence). '
                             'Pipeline sleeps for remaining time after each cycle. '
                             '0 = disabled (run back-to-back or use --interval).')
    parser.add_argument('--suspend',        action='store_true',
                        help='Use sudo rtcwake (suspend-to-RAM) during idle period instead of '
                             'time.sleep. Requires: sudo NOPASSWD for rtcwake. Saves ~95%% power '
                             'during idle. Combine with --cycle-period.')
    parser.add_argument('--min-free-gb',   type=float, default=0.0,
                        help='Auto-delete oldest PostProc directories matching --label when free '
                             'disk space drops below this value in GB (e.g. 5.0). '
                             '0 = disabled. Only deletes dirs whose name starts with --label.')
    parser.add_argument('--power-cycle-cmd', type=str, default=None,
                        help='Shell command that hard power-cycles the TDA (relay/smart '
                             'plug). Used as the last recovery-ladder level. Unset = level '
                             'disabled (no relay installed yet).')
    parser.add_argument('--min-tda-free-mb', type=int, default=200,
                        help='Pre-flight: auto-clean Trace_TDA_*.txt on the TDA when its '
                             'rootfs free space drops below this many MB.')
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
    if args.cycle_period > 0:
        print(f'  Cycle period     : {args.cycle_period}s  ({"suspend-to-RAM" if args.suspend else "time.sleep"} during idle)')
    if args.min_free_gb > 0:
        print(f'  Auto-cleanup     : delete oldest "{args.label}_*" dirs when free < {args.min_free_gb:.1f} GB')
    print(f'  PostProc dir     : {POSTPROC_DIR}')
    print(f'  Results dir      : {os.path.join(EDGE_DIR, "python-result")}')
    print(f'  PS source        : {args.ps_file if args.ps_file else ps_map_file + " (auto/ADI)"}')
    print(f'  Debug mode       : {"ON (SLC + range-profile enabled)" if args.debug else "OFF (PS metrics only)"}')
    print(f'  LoRa port        : {"disabled (--skip-lora)" if args.skip_lora else args.lora_port}')
    print(f'  Press Ctrl+C to stop after the current cycle.')

    os.makedirs(POSTPROC_DIR,   exist_ok=True)
    os.makedirs(JSON_FILES_DIR, exist_ok=True)

    policy = tda_recovery.RecoveryPolicy(args.tda_ip,
                                         power_cycle_cmd=args.power_cycle_cmd,
                                         sleep_fn=_ladder_sleep)
    stats = {'ok': 0, 'failed': 0}

    cycle = 0
    while not shutdown_flag:
        cycle += 1
        t_start = time.time()

        print(f'\n{"#"*60}')
        print(f'# CYCLE {cycle:4d}   [{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]')
        print(f'{"#"*60}')

        # ── 0. Pre-flight (TDA reachable, apps.out alive, rootfs not full) ──
        if not tda_recovery.preflight(args.tda_ip, min_free_mb=args.min_tda_free_mb):
            stats['failed'] += 1
            _step(f'Pre-flight failed — recovery: {policy.on_failure()}')
            continue

        # ── 1. Capture ──────────────────────────────────────────────
        t1 = _step_start(f'Step 1 — Capture ({args.duration}s)')
        capture_dir = run_capture(args.duration, args.tda_ip, args.label)
        if capture_dir is None:
            stats['failed'] += 1
            _step(f'Capture failed — recovery: {policy.on_failure()}')
            continue
        policy.on_success()
        stats['ok'] += 1
        _step_done('Step 1 — Capture', t1)

        if shutdown_flag:
            break

        # ── 2. Transfer ─────────────────────────────────────────────
        if not args.skip_transfer:
            t2 = _step_start(f'Step 2 — Transfer ({capture_dir})')
            ok = transfer_data(capture_dir, args.tda_ip)
            if not ok:
                print('[PIPELINE] Transfer failed — skipping processing for this cycle')
                if args.interval > 0:
                    time.sleep(args.interval)
                continue
            _step_done('Step 2 — Transfer', t2)

            # Verify essential binary files arrived — mimo.py can exit 0 with
            # an empty TDA directory when the hardware failed to write data.
            idx_file = os.path.join(POSTPROC_DIR, capture_dir, 'master_0000_idx.bin')
            if not os.path.isfile(idx_file):
                print(f'[PIPELINE] ERROR: master_0000_idx.bin missing in {capture_dir} '
                      f'— capture produced no data. Removing empty dir, retrying in 10s...')
                shutil.rmtree(os.path.join(POSTPROC_DIR, capture_dir), ignore_errors=True)
                time.sleep(10)
                continue
        else:
            _step('Step 2 — Transfer skipped (--skip-transfer)')

        if shutdown_flag:
            break

        # ── 3. SLC + Range Profile (debug mode only) ────────────────
        if args.debug:
            t3 = _step_start('Step 3 — Edge Processing (SLC + range-profile)')
            run_processing(capture_dir)
            _step_done('Step 3 — Edge Processing', t3)
        else:
            _step('Step 3 — Edge Processing skipped (add --debug to enable)')

        if shutdown_flag:
            break

        # ── 4. PS Monitoring ────────────────────────────────────────
        if not args.skip_ps:
            t4 = _step_start('Step 4 — PS Monitoring')
            run_ps_monitoring(capture_dir, ps_map_file, args.ps_file)
            _step_done('Step 4 — PS Monitoring', t4)
        else:
            _step('Step 4 — PS Monitoring skipped (--skip-ps)')

        if shutdown_flag:
            break

        # ── 5. LoRa uplink (store-and-forward) ──────────────────────
        t5 = _step_start('Step 5 — LoRa Uplink')
        run_lora_step(capture_dir, args.lora_port, args.lora_appkey,
                      skip_send=args.skip_lora)
        _step_done('Step 5 — LoRa Uplink', t5)

        # ── Auto-cleanup (disk space management) ────────────────────
        if args.min_free_gb > 0:
            _auto_cleanup(POSTPROC_DIR, args.label, args.min_free_gb)

        elapsed = time.time() - t_start
        print(f'\n{"─"*60}')
        print(f'  Cycle {cycle} completed  |  Total: {elapsed:.1f}s  |  {_ts()}')
        free_now = _free_gb(POSTPROC_DIR)
        print(f'  Disk free        : {free_now:.1f} GB')
        total = stats['ok'] + stats['failed']
        print(f'  Capture success  : {stats["ok"]}/{total} cycles '
              f'({100.0 * stats["ok"] / max(1, total):.0f}%)')
        print(f'{"─"*60}')

        if shutdown_flag:
            break

        if args.cycle_period > 0:
            idle = args.cycle_period - elapsed
            if idle > 10:
                _do_idle_sleep(idle, args.suspend)
            else:
                _step(f'Cycle took {elapsed:.0f}s (> cycle_period {args.cycle_period:.0f}s) — starting next immediately')
        elif args.interval > 0:
            _step(f'Waiting {args.interval}s before next cycle...')
            time.sleep(args.interval)

    print('\n[PIPELINE] Pipeline stopped cleanly.')


if __name__ == '__main__':
    main()
