#!/usr/bin/env python3
"""
Persistent-session MIMO Radar Pipeline  (Architecture A)

Difference vs pipeline.py
-------------------------
  pipeline.py           : spawns `mimo.py --num-loops 1` EVERY cycle → a fresh process that
                          re-runs the FULL radar init (firmware download to 4 chips +
                          RF power-up + rlRfInit calibration) on every single cycle.
  pipeline-persistent.py: initialises the radar ONCE (mmw_set_config + mmw_init), then loops
                          arm → start_frame → stop_frame → dearm per capture WITHOUT re-init.

Why
---
TI's documented sequence (DFP User Guide Fig 14-16, and the reference sample
`mmWaveLink_Cascade_Monitoring :: MMWL_App`) is 2-phase: a HEAVY init done ONCE
(firmware download, RF power-up, rfInit calibration) followed by a LIGHT, repeatable
`sensorStart` / `sensorStop`.  Re-running the heavy phase every cycle (as pipeline.py does)
adds ~85-95 s overhead/cycle and gives 3x the chances of an RF-init `-8` timeout per cycle
(one each at RL_MSS_POWERUP_COMPLETE, RL_RF_POWERUP_COMPLETE, RL_RF_AE_INITCALIBSTATUS_SB).
Initialising once removes both problems.  See TIDEP-01012.md §7.2.

Trade-off
---------
The radar stays powered between captures (no idle power-cycle).  Energy autonomy is already
~4.6x at continuous load (paperA_progress_and_decisions.md), so this is acceptable.  To
measure power-cycle energy instead, use pipeline.py (per-cycle re-init) or a relay-based
variant — see the note at the bottom of this file.

Post-capture steps (transfer / processing / PS monitoring / LoRa / cleanup / idle) are reused
verbatim from pipeline.py so the two pipelines are directly comparable.

Usage (mirrors pipeline.py)
---------------------------
    python3 pipeline-persistent.py --duration 10 --label BridgeSpan \
        --ps-file ~/IoSAR-EdgeProcessing/ps_manual_bridge.json --cycle-period 900

Press Ctrl+C to stop gracefully after the current cycle completes.
"""

import argparse
import os
import shutil
import time
from datetime import datetime

# Reuse the post-capture steps + constants from pipeline.py so both pipelines stay identical.
# (Importing pipeline registers its SIGINT/SIGTERM handlers, which set pipeline.shutdown_flag.)
import pipeline as P

import mmwcas
from mimo import config_dict
from utility import check_captured_files, export_config_to_json


def _now_ms() -> str:
    """Wall-clock timestamp with millisecond precision (event timing / accelerometer sync)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ─────────────────────────────────────────────
# One-time radar initialisation (the HEAVY phase, done ONCE)
# ─────────────────────────────────────────────

def init_radar(tda_ip: str) -> bool:
    """Configure + initialise the radar once.

    This is the heavy phase: TDA connect → power-up (master then slaves) → firmware download
    → RF power-up → static/dynamic config → rlRfInit (calibration) → frame config.
    Equivalent to mimo.py's mmw_set_config()+mmw_init(), but kept alive across captures.
    """
    P._banner('INIT — Radar configure + init (ONCE)')

    status = mmwcas.mmw_set_config(config_dict)
    if status != 0:
        print(f'[PERSIST] ERROR: mmw_set_config failed (status {status})')
        return False

    status = mmwcas.mmw_init(tda_ip)
    if status != 0:
        print(f'[PERSIST] ERROR: mmw_init failed (status {status})')
        return False

    time.sleep(2)
    os.makedirs(P.JSON_FILES_DIR, exist_ok=True)
    P._step('Radar initialised — entering persistent capture loop')
    return True


# ─────────────────────────────────────────────
# Step 1 — Capture (NO re-init; only arm → frame → stop → dearm)
# ─────────────────────────────────────────────

def capture_once(duration: float, tda_ip: str, label: str) -> str | None:
    """Run one capture without re-initialising the radar.

    Returns the capture directory name, or None on failure.
    """
    timestamp   = datetime.now().strftime('%y%m%d_%H%M%S')
    capture_dir = f'{label}_{timestamp}'
    P._banner(f'STEP 1 — Capture (persistent, {duration}s)  {capture_dir}')

    # ── Arm TDA ───────────────────────────────────────────────────────
    print(f'[TS] ARM_TDA_begin   {_now_ms()}', flush=True)
    status = mmwcas.mmw_arming_tda(capture_dir)
    print(f'[TS] ARM_TDA_end     {_now_ms()}  status={status}', flush=True)
    if status != 0:
        print(f'[PERSIST] mmw_arming_tda failed (status {status})')
        return None
    time.sleep(2)

    # ── Start framing (master triggered last → FRAMING_end ≈ t0 capture) ─
    print(f'[TS] FRAMING_begin   {_now_ms()}', flush=True)
    status = mmwcas.mmw_start_frame()
    print(f'[TS] FRAMING_end     {_now_ms()}  status={status}  <-- t0 capture', flush=True)
    if status != 0:
        print(f'[PERSIST] mmw_start_frame failed (status {status})')
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
        return None

    print(f' Capturing... ({duration}s)', flush=True)
    time.sleep(duration)

    # ── Stop framing + de-arm ─────────────────────────────────────────
    print(f'[TS] STOP_FRAME      {_now_ms()}', flush=True)
    status = mmwcas.mmw_stop_frame()
    if status != 0:
        print(f'[PERSIST] WARNING: mmw_stop_frame failed (status {status})')
    status = mmwcas.mmw_dearming_tda()
    if status != 0:
        print(f'[PERSIST] WARNING: mmw_dearming_tda failed (status {status})')

    # ── Verify data exists on the TDA before declaring success ────────
    success, _, _ = check_captured_files(capture_dir, tda_ip)
    if not success:
        print('[PERSIST] WARNING: no files found on TDA — capture produced no data')
        return None

    # ── Write config JSON (transfer_data moves it into the capture dir) ─
    json_path = os.path.join(P.JSON_FILES_DIR, f'{capture_dir}.mmwave.json')
    export_config_to_json(config_dict, json_path)
    return capture_dir


# ─────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Persistent-session MIMO Radar Pipeline (init once, loop captures)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('-t', '--duration',  type=float, default=10.0,
                        help='Radar capture duration in seconds')
    parser.add_argument('--label',           type=str,   default='RPI_python',
                        help='Capture directory prefix (timestamp appended automatically)')
    parser.add_argument('--tda-ip',          type=str,   default=P.TDA_IP_DEFAULT,
                        help='TDA board IP address')
    parser.add_argument('-i', '--interval',  type=float, default=0.0,
                        help='Wait time between cycles in seconds (0 = no delay)')
    parser.add_argument('--debug',           action='store_true',
                        help='Also generate SLC image + range-profile after transfer')
    parser.add_argument('--skip-transfer',   action='store_true',
                        help='Skip SCP transfer step')
    parser.add_argument('--skip-ps',         action='store_true',
                        help='Skip PS monitoring step')
    parser.add_argument('--ps-file',         type=str, default=None,
                        help='Path to manually-selected PS JSON (skips ADI)')
    parser.add_argument('--reset-ps',        action='store_true',
                        help='Delete PS map so it is recomputed next cycle')
    parser.add_argument('--skip-lora',       action='store_true',
                        help='Skip LoRa uplink step')
    parser.add_argument('--lora-port',       type=str, default='/dev/ttyUSB0',
                        help='Serial port of Wio-E5 LoRa module')
    parser.add_argument('--lora-appkey',     type=str,
                        default='562AD0AB720BA25D830E20164D3CC1B3',
                        help='LoRaWAN APPKEY (32 hex chars)')
    parser.add_argument('--cycle-period',    type=float, default=0.0,
                        help='Target total time per cycle in seconds (RPi idles for the remainder)')
    parser.add_argument('--suspend',         action='store_true',
                        help='Use sudo rtcwake (suspend-to-RAM) during idle instead of time.sleep')
    parser.add_argument('--min-free-gb',     type=float, default=0.0,
                        help='Auto-delete oldest "<label>_*" PostProc dirs when free disk < this (GB)')
    parser.add_argument('--reinit-every',    type=int, default=0,
                        help='Force a full radar re-init every N cycles (0 = never; rely on '
                             'persistent session). Use a small value only if you observe drift.')
    args = parser.parse_args()

    ps_map_file = os.path.join(P.EDGE_DIR, 'ps_map.json')
    if args.reset_ps and args.ps_file is None and os.path.isfile(ps_map_file):
        os.remove(ps_map_file)
        print(f'[PERSIST] Deleted PS map: {ps_map_file}')

    print('╔══════════════════════════════════════════════════════════╗')
    print('║   PERSISTENT MIMO RADAR PIPELINE — IMRSL (init once)    ║')
    print('╚══════════════════════════════════════════════════════════╝')
    print(f'  Capture duration : {args.duration}s')
    print(f'  Capture label    : {args.label}')
    print(f'  TDA IP address   : {args.tda_ip}')
    if args.cycle_period > 0:
        print(f'  Cycle period     : {args.cycle_period}s  ({"suspend-to-RAM" if args.suspend else "time.sleep"} during idle)')
    if args.reinit_every > 0:
        print(f'  Re-init every    : {args.reinit_every} cycles')
    print(f'  PostProc dir     : {P.POSTPROC_DIR}')
    print(f'  PS source        : {args.ps_file if args.ps_file else ps_map_file + " (auto/ADI)"}')
    print(f'  Mode             : PERSISTENT (radar initialised ONCE, stays powered between captures)')
    print(f'  Press Ctrl+C to stop after the current cycle.')

    os.makedirs(P.POSTPROC_DIR,   exist_ok=True)
    os.makedirs(P.JSON_FILES_DIR, exist_ok=True)

    # ── One-time heavy init ───────────────────────────────────────────
    if not init_radar(args.tda_ip):
        print('[PERSIST] Initial radar init failed — aborting.')
        return

    cycle = 0
    while not P.shutdown_flag:
        cycle += 1
        t_start = time.time()

        print(f'\n{"#"*60}')
        print(f'# CYCLE {cycle:4d}   [{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]   (persistent)')
        print(f'{"#"*60}')

        # Optional periodic re-init (off by default — the whole point is to avoid this)
        if args.reinit_every > 0 and cycle > 1 and (cycle - 1) % args.reinit_every == 0:
            print(f'[PERSIST] Scheduled re-init (every {args.reinit_every} cycles)...')
            init_radar(args.tda_ip)

        # ── 1. Capture (no re-init) ──────────────────────────────────
        t1 = P._step_start(f'Step 1 — Capture ({args.duration}s)')
        capture_dir = capture_once(args.duration, args.tda_ip, args.label)
        if capture_dir is None:
            print('[PERSIST] Capture failed — attempting software re-init (recovery)...')
            time.sleep(5)
            if not init_radar(args.tda_ip):
                print('[PERSIST] Re-init failed — waiting 15s before next attempt...')
                time.sleep(15)
            continue
        P._step_done('Step 1 — Capture', t1)

        if P.shutdown_flag:
            break

        # ── 2. Transfer ─────────────────────────────────────────────
        if not args.skip_transfer:
            t2 = P._step_start(f'Step 2 — Transfer ({capture_dir})')
            ok = P.transfer_data(capture_dir, args.tda_ip)
            if not ok:
                print('[PERSIST] Transfer failed — skipping rest of this cycle')
                if args.interval > 0:
                    time.sleep(args.interval)
                continue
            P._step_done('Step 2 — Transfer', t2)

            idx_file = os.path.join(P.POSTPROC_DIR, capture_dir, 'master_0000_idx.bin')
            if not os.path.isfile(idx_file):
                print(f'[PERSIST] ERROR: master_0000_idx.bin missing in {capture_dir} '
                      f'— removing empty dir, retrying next cycle...')
                shutil.rmtree(os.path.join(P.POSTPROC_DIR, capture_dir), ignore_errors=True)
                continue
        else:
            P._step('Step 2 — Transfer skipped (--skip-transfer)')

        if P.shutdown_flag:
            break

        # ── 3. SLC + range profile (debug only) ─────────────────────
        if args.debug:
            t3 = P._step_start('Step 3 — Edge Processing (SLC + range-profile)')
            P.run_processing(capture_dir)
            P._step_done('Step 3 — Edge Processing', t3)
        else:
            P._step('Step 3 — Edge Processing skipped (add --debug to enable)')

        if P.shutdown_flag:
            break

        # ── 4. PS Monitoring ────────────────────────────────────────
        if not args.skip_ps:
            t4 = P._step_start('Step 4 — PS Monitoring')
            P.run_ps_monitoring(capture_dir, ps_map_file, args.ps_file)
            P._step_done('Step 4 — PS Monitoring', t4)
        else:
            P._step('Step 4 — PS Monitoring skipped (--skip-ps)')

        if P.shutdown_flag:
            break

        # ── 5. LoRa uplink ──────────────────────────────────────────
        if not args.skip_lora:
            t5 = P._step_start('Step 5 — LoRa Uplink')
            P.run_lora_send(capture_dir, args.lora_port, args.lora_appkey)
            P._step_done('Step 5 — LoRa Uplink', t5)
        else:
            P._step('Step 5 — LoRa Uplink skipped (--skip-lora)')

        # ── Auto-cleanup ────────────────────────────────────────────
        if args.min_free_gb > 0:
            P._auto_cleanup(P.POSTPROC_DIR, args.label, args.min_free_gb)

        elapsed = time.time() - t_start
        print(f'\n{"─"*60}')
        print(f'  Cycle {cycle} completed  |  Total: {elapsed:.1f}s  |  {P._ts()}')
        print(f'  Disk free        : {P._free_gb(P.POSTPROC_DIR):.1f} GB')
        print(f'{"─"*60}')

        if P.shutdown_flag:
            break

        # ── Idle until next cycle ───────────────────────────────────
        if args.cycle_period > 0:
            idle = args.cycle_period - elapsed
            if idle > 10:
                P._do_idle_sleep(idle, args.suspend)
            else:
                P._step(f'Cycle took {elapsed:.0f}s (> cycle_period {args.cycle_period:.0f}s) — next immediately')
        elif args.interval > 0:
            P._step(f'Waiting {args.interval}s before next cycle...')
            time.sleep(args.interval)

    # ── Teardown ──────────────────────────────────────────────────────
    # If the powerOff teardown is exposed in mmwcas (see TIDEP-01012.md §2.1b / §7 draft),
    # call it here to power off devices cleanly (slaves first, master last) — mirroring TI's
    # MMWL_App. Guarded so this file works whether or not mmwcas has been rebuilt with it.
    if hasattr(mmwcas, 'mmw_power_off'):
        print('[PERSIST] Power-off teardown (slaves → master)...')
        try:
            mmwcas.mmw_power_off()
        except Exception as exc:
            print(f'[PERSIST] WARNING: power-off teardown failed: {exc}')

    print('\n[PERSIST] Pipeline stopped cleanly.')


if __name__ == '__main__':
    main()


# ═════════════════════════════════════════════════════════════════════
# NOTE — measuring power-cycle (Architecture B) energy
# ═════════════════════════════════════════════════════════════════════
# This file keeps the radar powered between captures.  To measure DAILY ENERGY for the
# power-cycle-each-cycle architecture you need to physically cut TIDEP power during idle
# (12 V / 5 A via a relay/SSR/MOSFET on RPi GPIO — see TIDEP-01012.md §2.2-A).  The existing
# pipeline.py already re-inits fully every cycle, so a relay variant can be built on top of it
# by switching the relay OFF during the idle period and ON (+ warm-up wait) before each cycle.
# Until the relay is wired, power-cycle daily energy can only be ESTIMATED from per-phase
# wattage, not measured.
