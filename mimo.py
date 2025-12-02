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
        
        try:
            status = mmwcas.mmw_arming_tda(dirName)
            assert status == 0, ValueError
            time.sleep(2)
            status = mmwcas.mmw_start_frame()
            assert status == 0, ValueError

            time.sleep(record_duration)

            status = mmwcas.mmw_stop_frame()
            assert status == 0, ValueError
            status = mmwcas.mmw_dearming_tda()
            assert status == 0, ValueError
            time.sleep(2)
            print(f"Recording {recording_count} completed")
        except Exception as e:
            print(f"Recording {recording_count} failed! Cleaning up and retrying...")
            print(f"Error: {e}")
            try:
                mmwcas.mmw_stop_frame()
                mmwcas.mmw_dearming_tda()
                time.sleep(2)
            except:
                pass
            # Loop continues to next recording

except KeyboardInterrupt:
    print("\n\n=== Stopped by user (Ctrl+C) ===")
    print(f"Total recordings completed: {recording_count}")
except Exception as e:
    print(f"\n\n=== Error occurred ===")
    print(f"Error: {e}")
    print(f"Total recordings completed: {recording_count}")
