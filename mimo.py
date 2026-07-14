import time
import argparse
from datetime import datetime
import sys
import mmwcas
import signal
from utility import export_config_to_json
from utility import check_captured_files
from utility import signal_handler
import os


def _now_ms() -> str:
    """Wall-clock timestamp with millisecond precision (for event timing / accel sync)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _try_with_backoff(fn, name, backoffs=(5, 15, 45)):
    """Run fn() -> status up to len(backoffs) times.
    Sleeps backoffs[i] after the i-th failure. True on first success."""
    for i, wait in enumerate(backoffs):
        status = fn()
        if status == 0:
            return True
        last = (i == len(backoffs) - 1)
        print(f'{name} failed (status: {status})'
              + (' — giving up' if last else f' — retrying in {wait}s'))
        if not last:
            time.sleep(wait)
    return False


config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 77,           # Chirp start frequency in GHz
            "frequencySlope": 90,           # Frequency slope in MHz/us  (BridgeSpan_260603)
            "idleTime": 3.5,                # Chirp idle time in us
            "adcStartTime": 4.45,           # ADC start time in us
            "numAdcSamples": 120,           # Number of ADC samples per chirp
            "adcSamplingFrequency": 6500,   # ADC sampling frequency in ksps
            "rampEndTime": 23.65,           # Chirp ramp end time in us
            "rxGain": 48,                   # dB
            "txStartTime": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numLoops": 10,                 # Number of chirp loops per frame
            "numFrames": 0,                 # Number of frames to record (0 = duration-controlled)
            "framePeriodicity": 30,         # Frame periodicity in ms → Fs = 33.33 Hz
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}

# Global flag for graceful shutdown
shutdown_flag = False

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='TIDEP-01012 MIMO Cascade Radar Control IMRSL')
    parser.add_argument('-d', '--directory', 
                        type=str, 
                        default='mmwave_python',
                        help='Base directory name for data capture (default: mmwave_python)')
    parser.add_argument('-t', '--duration', 
                        type=float, 
                        default=10.0,
                        help='Recording duration in seconds (default: 10.0)')
    parser.add_argument('--tda-ip',
                        type=str,
                        default='192.168.33.180',
                        help='TDA board IP address (default: 192.168.33.180)')
    parser.add_argument('-n', '--num-loops',
                        type=int,
                        default=1,
                        help='Number of capture loops (default: 1, 0 = infinite until Ctrl+C)')
    parser.add_argument('-i', '--inter-loop-time',
                        type=float,
                        default=60.0,
                        help='Delay between capture loops in seconds (default: 60.0)')
    parser.add_argument('--finite-framing', action='store_true',
                        help='Program numFrames from --duration (TI official workflow) '
                             'instead of infinite framing + manual StopFrame. '
                             'Eliminates -2 stop-frame errors. Default: off.')
    parser.add_argument('--config', type=str, default=None,
                        help='Radar-config TOML. Merges [mimo.profile]/[mimo.frame]/'
                             '[mimo.channel] over the built-in default (config_dict). '
                             'Without it, the built-in default is used.')

    args = parser.parse_args()

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Validate arguments
    if args.num_loops < 0:
        print("Error: --num-loops must be >= 0")
        sys.exit(1)

    # Resolve radar config: merged TOML if --config given, else the default.
    cfg = config_dict
    if args.config:
        import radar_config
        try:
            cfg = radar_config.load_and_merge(args.config, config_dict)
        except (FileNotFoundError, ValueError) as exc:
            print(f"--config: {exc}")
            sys.exit(2)
        except Exception as exc:                      # tomllib.TOMLDecodeError, etc.
            print(f"--config: failed to parse {args.config}: {exc}")
            sys.exit(2)
        print(f"Loaded radar config: {args.config}")

    # Generate capture directory name with timestamp (2-digit year, e.g. 260510_141438)
    timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
    capture_dir = f"{args.directory}_{timestamp}"

    print(f"Capture directory: {capture_dir}")
    print(f"Capture duration: {args.duration} seconds")
    print(f"Number of loops  : {'Infinite (until Ctrl+C)' if args.num_loops == 0 else args.num_loops}")
    if args.num_loops != 1:
        print(f"Inter-loop delay : {args.inter_loop_time} seconds")

    if args.finite_framing:
        from utility import finite_num_frames
        fp = cfg["mimo"]["frame"]["framePeriodicity"]
        try:
            nf = finite_num_frames(args.duration, fp)
        except ValueError as exc:
            print(f"--finite-framing: {exc}")
            sys.exit(1)
        cfg["mimo"]["frame"]["numFrames"] = nf
        print(f"Finite framing: numFrames={nf} ({args.duration}s @ {fp}ms/frame)")

    # Configure radar
    status = mmwcas.mmw_set_config(cfg)
    if status != 0:
        print(f"Configuration error: {status}")
        sys.exit(2)
    
    # Initialize radar (heavy phase). With the non-exiting mmwcas, a failure
    # here returns a status code instead of killing the interpreter.
    status = mmwcas.mmw_init(args.tda_ip)
    if status != 0:
        print(f"mmw_init failed (status: {status}) — powering off and exiting")
        if hasattr(mmwcas, "mmw_power_off"):
            try:
                mmwcas.mmw_power_off()
            except Exception as e:
                print(f"[MMWCAS] WARNING: power-off after failed init failed: {e}")
        sys.exit(2)
    time.sleep(2)

    os.makedirs("mmwave_json_files", exist_ok=True)
    # Capture loop
    loop_count = 0
    infinite_mode = (args.num_loops == 0)
    
    try:
        while True:
            # Check if we should continue
            if not infinite_mode and loop_count >= args.num_loops:
                break
            
            if shutdown_flag:
                print("\n Shutdown requested. Exiting capture loop...")
                break
            
            loop_count += 1
            
            # Generate capture directory name with timestamp (2-digit year)
            timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
            capture_dir = f"{args.directory}_{timestamp}"
            
            print("\n" + "="*60)
            print(f"CAPTURE LOOP {loop_count}" + (" (INFINITE MODE)" if infinite_mode else f" of {args.num_loops}"))
            print("="*60)
            print(f"Capture directory: {capture_dir}")
            print(f"Recording duration: {args.duration} seconds")
            print("="*60)
            
            # Arm TDA for capture (light retry — see design spec Part 1d)
            print(f"[TS] ARM_TDA_begin   {_now_ms()}", flush=True)
            if not _try_with_backoff(lambda: mmwcas.mmw_arming_tda(capture_dir),
                                     'mmw_arming_tda'):
                continue  # Skip to next loop
            print(f"[TS] ARM_TDA_end     {_now_ms()}", flush=True)
            time.sleep(2)

            # Start frame capture (light retry)
            print(f"[TS] FRAMING_begin   {_now_ms()}", flush=True)
            if not _try_with_backoff(mmwcas.mmw_start_frame, 'mmw_start_frame'):
                mmwcas.mmw_stop_frame()
                mmwcas.mmw_dearming_tda()
                continue  # Skip to next loop
            # FRAMING_end ≈ t0 of the actual capture (master is triggered last)
            print(f"[TS] FRAMING_end     {_now_ms()}  <-- t0 capture", flush=True)

            print(f"\n Capturing... ({args.duration}s)")
            # Finite framing: frames stop by themselves after numFrames;
            # +2s margin lets the last frame land before de-arm.
            time.sleep(args.duration + (2.0 if args.finite_framing else 0.0))

            # Stop frame capture
            if args.finite_framing:
                print(f"[TS] STOP_FRAME skipped (finite framing) {_now_ms()}", flush=True)
            else:
                print(f"[TS] STOP_FRAME      {_now_ms()}", flush=True)
                status = mmwcas.mmw_stop_frame()
                if status != 0:
                    print(f"mmw_stop_frame failed (status: {status})")
                    time.sleep(1)
                    continue  # Skip to next loop
            
            # De-arm TDA
            status = mmwcas.mmw_dearming_tda()
            if status != 0:
                print(f"mmw_dearming_tda failed (status: {status})")
                time.sleep(1)
                continue  # Skip to next loop
    
            # Check if files were actually captured
            print("\n" + "="*60)
            print("Verifying data capture...")
            print("="*60)
            
            success, file_count, files = check_captured_files(capture_dir, args.tda_ip)
            
            if not success:
                print("\n  WARNING: No files found in capture directory!")
                print("\n  Skipping .mmwave.json generation.")
                #sys.exit(1)
            
            # Generate configuration JSON file only if capture was successful
            json_filename = os.path.join("mmwave_json_files", f"{capture_dir}.mmwave.json")
            print(f"\nGenerating configuration file: {json_filename}")
            export_config_to_json(cfg, json_filename)
            
            print("\n" + "="*60)
            print(f"Data capture {capture_dir} completed successfully!")
            print("="*60)

    except KeyboardInterrupt:
        print("\n\nCapture interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nError during capture: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Clean teardown: power off devices (slaves first, master last) — mirrors TI's
        # reference MMWL_App, which always powers off before exit. This leaves the radar in a
        # known state so the next run starts clean (reduces RF init/enable -8 failures).
        # No-op until mmwcas is rebuilt with mmw_power_off (make build).
        if hasattr(mmwcas, "mmw_power_off"):
            try:
                mmwcas.mmw_power_off()
                print("[MMWCAS] Radar powered off (teardown).")
            except Exception as e:
                print(f"[MMWCAS] WARNING: power-off teardown failed: {e}")

if __name__ == "__main__":
    main()
