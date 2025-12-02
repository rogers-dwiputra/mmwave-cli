import time
import mmwcas
from datetime import datetime

config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 77,           # GHz
            "frequencySlope": 15,           # MHz/us
            "idleTime": 5,                # us
            "adcStartTime": 6,           # us
            "rampEndTime": 40,           # us
            "txStartTime": 0,               # us
            "numAdcSamples": 256,           # samples per chirp
            "adcSamplingFrequency": 8000,   # ksps
            "rxGain": 48,                   # dB
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numFrames": 0,                # 0 for infinite, 10 in Lua script
            "numLoops": 16,                 # chirps per frame
            "framePeriodicity": 100,        # ms
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}
record_duration = 2
max_retries = 3  # Maximum number of retries per recording attempt

status = mmwcas.mmw_set_config(config_dict)
if status != 0:
    print(status)
    raise ValueError(f"{status}")

status = mmwcas.mmw_init()
assert status == 0, ValueError
time.sleep(2)

recording_count = 0
try:
    while True:
        recording_count += 1
        print(f"\n=== Recording {recording_count} ===")
        dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
        print(f"dirName: {dirName}")
        
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                status = mmwcas.mmw_arming_tda(dirName)
                if status != 0:
                    raise Exception(f"Arming TDA failed with status {status}")
                
                time.sleep(2)
                
                status = mmwcas.mmw_start_frame()
                if status != 0:
                    raise Exception(f"Start frame failed with status {status}")

                time.sleep(record_duration)

                status = mmwcas.mmw_stop_frame()
                if status != 0:
                    print(f"Warning: Stop frame returned status {status}")
                
                status = mmwcas.mmw_dearming_tda()
                if status != 0:
                    print(f"Warning: Dearming TDA returned status {status}")
                
                time.sleep(2)
                print(f"Recording {recording_count} completed successfully")
                success = True
                
            except Exception as e:
                retry_count += 1
                print(f"Recording {recording_count} failed on attempt {retry_count}/{max_retries}")
                print(f"Error: {e}")
                
                # Cleanup before retry
                try:
                    mmwcas.mmw_stop_frame()
                except:
                    pass
                
                try:
                    mmwcas.mmw_dearming_tda()
                except:
                    pass
                
                if retry_count < max_retries:
                    print(f"Waiting 3 seconds before retry...")
                    time.sleep(3)
                    # Generate new directory name for retry
                    dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
                    print(f"Retrying with new dirName: {dirName}")
                else:
                    print(f"Recording {recording_count} failed after {max_retries} attempts. Moving to next recording.")
        
        # Small delay between recordings
        time.sleep(1)

except KeyboardInterrupt:
    print("\n\n=== Stopped by user (Ctrl+C) ===")
    print(f"Total recordings attempted: {recording_count}")
except Exception as e:
    print(f"\n\n=== Unexpected error occurred ===")
    print(f"Error: {e}")
    print(f"Total recordings attempted: {recording_count}")
finally:
    # Final cleanup
    try:
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
    except:
        pass