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

config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 77,           # Chirp start frequency in GHz
            "frequencySlope": 79.0327,      # Frequency slope in MHz/us
            "idleTime": 5,                  # Chrip Idle time in us
            "adcStartTime": 6,              # ADC start time in us
            "numAdcSamples": 256,           # Number of ADC samples per chirp
            "adcSamplingFrequency": 8000,   # ADC sampling frequency in ksps
            "rampEndTime": 40,              # Chirp ramp end time in us
            "rxGain": 48,                   # dB
            "txStartTime": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numLoops": 16,                 # Number of chirp loop per frame
            "numFrames": 0,                 # Number of frames to record
            "framePeriodicity": 100,        # Frame periodicity in ms (Inter_Frame_Interval)
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
    
    args = parser.parse_args()

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Validate arguments
    if args.num_loops < 0:
        print("Error: --num-loops must be >= 0")
        sys.exit(1)
    
    # Generate capture directory name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    capture_dir = f"{args.directory}_{timestamp}"
    
    print(f"Capture directory: {capture_dir}")
    print(f"Capture duration: {args.duration} seconds")
    print(f"Number of loops  : {'Infinite (until Ctrl+C)' if args.num_loops == 0 else args.num_loops}")
    if args.num_loops != 1:
        print(f"Inter-loop delay : {args.inter_loop_time} seconds")
    
    # Configure radar
    status = mmwcas.mmw_set_config(config_dict)
    if status != 0:
        print(f"Configuration error: {status}")
        raise ValueError(f"mmw_set_config failed with status {status}")
    
    # Initialize radar
    status = mmwcas.mmw_init()
    assert status == 0, ValueError("mmw_init failed")
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
            
            # Generate capture directory name with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            capture_dir = f"{args.directory}_{timestamp}"
            
            print("\n" + "="*60)
            print(f"CAPTURE LOOP {loop_count}" + (" (INFINITE MODE)" if infinite_mode else f" of {args.num_loops}"))
            print("="*60)
            print(f"Capture directory: {capture_dir}")
            print(f"Recording duration: {args.duration} seconds")
            print("="*60)
            
            # Arm TDA for capture
            status = mmwcas.mmw_arming_tda(capture_dir)
            if status != 0:
                print(f"mmw_arming_tda failed (status: {status})")
                time.sleep(1)
                continue  # Skip to next loop
            time.sleep(2)
            
            # Start frame capture
            status = mmwcas.mmw_start_frame()
            if status != 0:
                print(f"mmw_start_frame failed (status: {status})")
                time.sleep(1)
                continue  # Skip to next loop
            
            print(f"\n Capturing... ({args.duration}s)")
            time.sleep(args.duration)

            # Stop frame capture
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
            export_config_to_json(config_dict, json_filename)
            
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

if __name__ == "__main__":
    main()
