import time
import mmwcas
import argparse
from datetime import datetime

def get_timestamp():
    """Get timestamp: YYYYMMDD_HHMMSS_millisecond"""
    now = datetime.now()
    return now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond // 1000:03d}"

def record(capture_dir_base, duration_minutes):
    """Perform a recording"""
    capture_dir = f"{capture_dir_base}_{get_timestamp()}"
    duration_seconds = duration_minutes * 60
    
    print(f"\nRecording to: /mnt/ssd/{capture_dir}")
    print(f"Duration: {duration_minutes} minutes")
    
    time.sleep(2)
    status = mmwcas.mmw_arming_tda(capture_dir)
    if status != 0:
        print(f"ERROR: Arming failed")
        return status
    
    time.sleep(2)
    status = mmwcas.mmw_start_frame()
    if status != 0:
        print(f"ERROR: Start frame failed")
        return status
    
    print("Recording...")
    time.sleep(duration_seconds)
    
    mmwcas.mmw_stop_frame()
    mmwcas.mmw_dearming_tda()
    
    print(f"Complete! Saved to: /mnt/ssd/{capture_dir}")
    time.sleep(2)
    return 0

def main():
    parser = argparse.ArgumentParser(description='MMWave EVM Python Control')
    parser.add_argument('-i', '--ip-addr', default='192.168.33.180',
                       help='IP Address of MMWCAS DSP board')
    parser.add_argument('-p', '--port', type=int, default=5001,
                       help='Port number')
    parser.add_argument('-d', '--capture-dir', default='capture',
                       help='Capture directory name')
    parser.add_argument('-t', '--time', type=float, default=1.0,
                       help='Recording duration in minutes')
    
    args = parser.parse_args()
    
    # Convert minutes to seconds
    record_duration = args.time * 60
    
    # Initialize
    # Configure radar parameters
    config = {
        "mimo": {
            "profile": {
                "id": 0,
                "startFrequency": 79.0,           # GHz
                "frequencySlope": 65.854,        # MHz/us
                "idleTime": 3,                  # us
                "adcStartTime": 3,              # us
                "rampEndTime": 28,              # us
                "numAdcSamples": 512,
                "adcSamplingFrequency": 22500,     # ksps
                "rxGain": 48                      # dB
            },
            "frame": {
                "numFrames": 0,                   # 0 = infinite
                "numLoops": 10,
                "framePeriodicity": 50.0         # ms
            },
            "channel": {
                "rxChannelEn": 0x0F,              # All 4 RX channels
                "txChannelEn": 0x07               # All 3 TX channels
            }
        }
    }
    print("Configuring radar...")
    mmwcas.mmw_set_config(config)
    mmwcas.mmw_init(ip_addr=args.ip_addr, port=args.port)
    print("Configuration complete. Radar ready!\n")

    print("You can now call record() function. Examples:")
    print('  record("outdoor1", 2)    # 2 minutes')
    print('  record("indoor", 1.5)    # 1.5 minutes')
    print('  record("highway", 3)     # 3 minutes')
    
    # # Record 1
    # time.sleep(2)
    # capture_dir = f"{args.capture_dir}_{get_timestamp()}"
    # mmwcas.mmw_arming_tda(capture_dir)
    # time.sleep(2)
    # mmwcas.mmw_start_frame()
    
    # time.sleep(record_duration)
    
    # mmwcas.mmw_stop_frame()
    # mmwcas.mmw_dearming_tda()

    # Record 2
    # status = mmwcas.mmw_arming_tda("outdoor1")
    # assert status==0,ValueError
    # time.sleep(2)
    # status = mmwcas.mmw_start_frame()
    # assert status==0,ValueError

    # time.sleep(record_duration)

    # status=mmwcas.mmw_stop_frame()
    # assert status==0,ValueError
    # status=mmwcas.mmw_dearming_tda()
    # assert status==0,ValueError
    
    # print(f"Recording saved to /mnt/ssd/{capture_dir}")

if __name__ == "__main__":
    main()
