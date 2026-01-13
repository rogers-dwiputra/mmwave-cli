import time
import mmwcas
import sys
from datetime import datetime
from config_export import export_config_to_json

# Configuration dictionary
config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "start_freq": 79,           # Chirp start frequency in GHz
            "slope": 33,           # Frequency slope in MHz/us
            "idle_time": 4,                  # Chrip Idle time in us
            "adc_start_time": 5,              # ADC start time in us
            "adc_samples": 256,           # Number of ADC samples per chirp
            "sample_freq": 15000,  # ADC sampling frequency in ksps
            "ramp_end_time": 23,              # Chirp ramp end time in us
            "rx_gain": 48,                   # dB
            "txStartTimeUSec": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "nchirp_loops": 16,                 # Number of chirp loop per frame
            "nframes_master": 0,                 # Number of frames to record
            "Inter_Frame_Interval": 50,         # Frame periodicity in ms (Inter_Frame_Interval)
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}

record_duration = 2
max_retries = 3  # Maximum number of retries per recording attempt

def log_message(log_file, message):
    """Write a timestamped message to log file and print to console"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    try:
        with open(log_file, 'a') as f:
            f.write(log_line + '\n')
    except IOError as e:
        print(f"WARNING: Failed to write to log file: {e}")

# Initialize the system
status = mmwcas.mmw_set_config(config_dict)
if status != 0:
    print(status)
    raise ValueError(f"{status}")

status = mmwcas.mmw_init()
assert status == 0, ValueError
time.sleep(2)

# Generate JSON configuration file and log file once at start
session_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
json_filename = f"Continuous_{session_timestamp}.mmwave.json"
log_filename = f"Continuous_{session_timestamp}.log"

try:
    export_config_to_json(config_dict, json_filename)
    print(f"Configuration JSON saved: {json_filename}")
    log_message(log_filename, f"=== Session Started ===")
    log_message(log_filename, f"Configuration JSON: {json_filename}")
    log_message(log_filename, f"Record duration: {record_duration} seconds")
except Exception as e:
    print(f"ERROR: Failed to create JSON config: {e}")

recording_count = 0
try:
    while True:
        recording_count += 1
        log_message(log_filename, f"\n=== Recording {recording_count} Started ===")
        dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
        log_message(log_filename, f"Directory: {dirName}")
        print(f"\n=== Recording {recording_count}: {dirName} ===")
        
        try:
            status = mmwcas.mmw_arming_tda(dirName)
            if status != 0:
                raise Exception(f"Arming TDA failed with status {status}")
            log_message(log_filename, "TDA armed successfully")
            
            time.sleep(2)
            
            status = mmwcas.mmw_start_frame()
            if status != 0:
                raise Exception(f"Start frame failed with status {status}")
            log_message(log_filename, "Frame started successfully")

            time.sleep(record_duration)
            log_message(log_filename, f"Recording completed ({record_duration}s)")

            status = mmwcas.mmw_stop_frame()
            if status != 0:
                raise Exception(f"Stop frame failed with status {status}")
            log_message(log_filename, "Frame stopped successfully")
            
            status = mmwcas.mmw_dearming_tda()
            if status != 0:
                raise Exception(f"Dearming TDA failed with status {status}")
            log_message(log_filename, "TDA de-armed successfully")
            
            time.sleep(2)
            log_message(log_filename, f"Recording {recording_count} completed successfully")
            print(f"Recording {recording_count} completed successfully")
            
        except Exception as e:
            error_msg = f"Recording {recording_count} failed: {e}"
            log_message(log_filename, f"ERROR: {error_msg}")
            log_message(log_filename, f"*** DO NOT USE FOR ANALYSIS: {dirName} ***")
            print(f"✗ {error_msg}")
            print(f"*** Flagged as corrupted: {dirName} ***")
            
            # Cleanup
            try:
                mmwcas.mmw_stop_frame()
                log_message(log_filename, "Cleanup: Frame stopped")
            except:
                pass
            
            try:
                mmwcas.mmw_dearming_tda()
                log_message(log_filename, "Cleanup: TDA de-armed")
            except:
                pass
            
            log_message(log_filename, "Moving to next recording")
            print("Moving to next recording...")
        
        # Small delay between recordings
        time.sleep(1)

except KeyboardInterrupt:
    log_message(log_filename, f"\n=== Session Stopped by user (Ctrl+C) ===")
    log_message(log_filename, f"Total recordings attempted: {recording_count}")
    print("\n\n=== Stopped by user (Ctrl+C) ===")
    print(f"Total recordings attempted: {recording_count}")
except Exception as e:
    log_message(log_filename, f"\n=== Unexpected error occurred ===")
    log_message(log_filename, f"Error: {e}")
    log_message(log_filename, f"Total recordings attempted: {recording_count}")
    print(f"\n\n=== Unexpected error occurred ===")
    print(f"Error: {e}")
    print(f"Total recordings attempted: {recording_count}")
finally:
    # Final cleanup
    try:
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
        log_message(log_filename, "Final cleanup completed")
    except:
        pass