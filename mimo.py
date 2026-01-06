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
            "startFrequency": 79,           # Chirp start frequency in GHz
            "frequencySlope": 33,           # Frequency slope in MHz/us
            "idleTime": 4,                  # Chrip Idle time in us
            "adcStartTime": 5,              # ADC start time in us
            "numAdcSamples": 256,           # Number of ADC samples per chirp
            "adcSamplingFrequency": 15000,  # ADC sampling frequency in ksps
            "rampEndTime": 23,              # Chirp ramp end time in us
            "rxGain": 48,                   # dB
            "txStartTime": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numLoops": 16,                 # Number of chirp loop per frame
            "numFrames": 0,                 # Number of frames to record
            "framePeriodicity": 50,         # Frame periodicity in ms (Inter_Frame_Interval)
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

# Generate JSON configuration file once before starting recordings
json_filename = "radar_config.mmwave.json"
try:
    export_config_to_json(config_dict, json_filename)
    print(f"Configuration JSON saved: {json_filename}")
except Exception as e:
    print(f"ERROR: Failed to create JSON config: {e}")

recording_count = 0
try:
    while True:
        recording_count += 1
        print(f"\n=== Recording {recording_count} ===")
        dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
        print(f"dirName: {dirName}")
        
        # Create log file name
        log_filename = f"{dirName}.txt"
        
        # Write initial log entry
        log_message(log_filename, f"=== Recording {recording_count} Started ===")
        log_message(log_filename, f"Directory: {dirName}")
        log_message(log_filename, f"Record duration: {record_duration} seconds")
        log_message(log_filename, f"Using configuration: {json_filename}")
        
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                log_message(log_filename, f"Attempt {retry_count + 1}/{max_retries}")
                
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
                    log_message(log_filename, f"Warning: Stop frame returned status {status}")
                else:
                    log_message(log_filename, "Frame stopped successfully")
                
                status = mmwcas.mmw_dearming_tda()
                if status != 0:
                    log_message(log_filename, f"Warning: Dearming TDA returned status {status}")
                else:
                    log_message(log_filename, "TDA de-armed successfully")
                
                time.sleep(2)
                log_message(log_filename, f"Recording {recording_count} completed successfully")
                print(f"Recording {recording_count} completed successfully")
                success = True
                
            except Exception as e:
                retry_count += 1
                error_msg = f"Recording {recording_count} failed on attempt {retry_count}/{max_retries}: {e}"
                log_message(log_filename, f"ERROR: {error_msg}")
                print(error_msg)
                
                # Cleanup before retry
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
                
                if retry_count < max_retries:
                    log_message(log_filename, f"Waiting 3 seconds before retry...")
                    print(f"Waiting 3 seconds before retry...")
                    time.sleep(3)
                    # Generate new directory name for retry
                    dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
                    log_message(log_filename, f"Retrying with new dirName: {dirName}")
                    print(f"Retrying with new dirName: {dirName}")
                else:
                    log_message(log_filename, f"Recording {recording_count} failed after {max_retries} attempts")
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