import time
import mmwcas
import argparse
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Run mmWave capture with configurable parameters")
    parser.add_argument("-d", "--dirname", type=str, default="outdoor",
                        help="Base directory name for recording")
    parser.add_argument("-i", "--ip", type=str, default="192.168.33.180",
                        help="Radar IP address")
    parser.add_argument("-t", "--time", type=int, default=2,
                        help="Record duration in seconds")
    parser.add_argument("-l", "--loops", type=int, default=3,
                        help="Number of capture loops")
    args = parser.parse_args()

    # Generate timestamp and directory name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = f"{args.dirname}_{timestamp}"

    print("=== mmWave Capture Start ===")
    print(f"Base Directory : {base_dir}")
    print(f"IP Address     : {args.ip}")
    print(f"Record Duration: {args.time} seconds")
    print(f"Number of Loops: {args.loops}")
    print("============================")

    config_dict = {}

    # Set config
    status = mmwcas.mmw_set_config(config_dict)
    if status != 0:
        raise ValueError(f"Config error: {status}")

    # Init radar with custom IP
    status = mmwcas.mmw_init(ip_addr=args.ip, port=5001)
    assert status == 0, ValueError(f"Init error: {status}")
    time.sleep(2)

    # Repeat N recordings
    for idx in range(args.loops):
	    print(f"\n[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Arming radar (loop {idx + 1})")

	    capture_time = datetime.now().strftime("%Y%m%d_%H%M%S")
	    dir_name = f"{args.dirname}_{capture_time}"
	    status = mmwcas.mmw_arming_tda(dir_name)
	    assert status == 0, ValueError(f"Arming error: {status}")
	    time.sleep(1)
	    
	    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Start frame -> Directory: {dir_name}")
	    status = mmwcas.mmw_start_frame()
	    assert status == 0, ValueError(f"Start frame error: {status}")

	    time.sleep(args.time)
	    
	    status=mmwcas.mmw_stop_frame()
	    assert status==0,ValueError
	    status=mmwcas.mmw_dearming_tda()
	    assert status==0,ValueError
	    time.sleep(1)

    print(f"\n[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Capture completed successfully.")

if __name__ == "__main__":
    main()

