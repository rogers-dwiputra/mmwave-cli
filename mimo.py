import time
import mmwcas
import sys
from datetime import datetime
from config_export import export_config_to_json

# Configuration dictionary - EXACTLY MATCHES WINDOWS .LUA CONFIG
config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "start_freq": 77,           # EXACT MATCH: 77 GHz
            "slope": 15.0148,           # EXACT MATCH: 15.0148 MHz/us (was 25 in old lua)
            "idle_time": 7,             # EXACT MATCH: 7 us
            "adc_start_time": 4.35,     # EXACT MATCH: 4.35 us (was 4.34)
            "adc_samples": 512,         # EXACT MATCH: 512 samples
            "sample_freq": 8000,        # EXACT MATCH: 8000 ksps
            "ramp_end_time": 68.97,     # EXACT MATCH: 68.97 us
            "rx_gain": 48,              # EXACT MATCH: 48 dB
            "txStartTimeUSec": 0,       # EXACT MATCH: 0 us
            "hpfCornerFreq1": 0,        # EXACT MATCH: 0 (175kHz)
            "hpfCornerFreq2": 0,        # EXACT MATCH: 0 (350kHz)
        },
        "frame": {
            "nchirp_loops": 10,         # EXACT MATCH: 10 chirp loops per frame
            "nframes_master": 0,        # EXACT MATCH: 0 (infinite frames)
            "nframes_slave": 0,         # EXACT MATCH: 0 (infinite frames)
            "Inter_Frame_Interval": 10, # EXACT MATCH: 10 ms frame periodicity
            "trigger_mode_master": 1,   # EXACT MATCH: Software trigger for master
            "trigger_mode_slave": 2,    # EXACT MATCH: Hardware trigger for slaves
        },
        "channel": {
            "rxChannelEn": 0x0F,        # Enable all 4 RX channels
            "txChannelEn": 0x07,        # Enable all 3 TX channels
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
print("=" * 80)
print("TDM-MIMO CASCADE RADAR INITIALIZATION")
print("=" * 80)
print(f"Start Frequency: {config_dict['mimo']['profile']['start_freq']} GHz")
print(f"Chirp Slope: {config_dict['mimo']['profile']['slope']} MHz/us")
print(f"ADC Start Time: {config_dict['mimo']['profile']['adc_start_time']} us")
print(f"Chirp Loops per Frame: {config_dict['mimo']['frame']['nchirp_loops']}")
print(f"Number of Frames: {config_dict['mimo']['frame']['nframes_master']} (0=infinite)")
print(f"Frame Interval: {config_dict['mimo']['frame']['Inter_Frame_Interval']} ms")
print(f"ADC Samples: {config_dict['mimo']['profile']['adc_samples']}")
print("=" * 80)

status = mmwcas.mmw_set_config(config_dict)
if status != 0:
    print(f"ERROR: Configuration failed with status {status}")
    raise ValueError(f"Configuration error: {status}")

print("\nInitializing mmWave cascade system...")
status = mmwcas.mmw_init()
if status != 0:
    print(f"ERROR: Initialization failed with status {status}")
    raise ValueError(f"Initialization error: {status}")

print("✓ Initialization successful!")
time.sleep(2)

# Generate JSON configuration file and log file once at start
session_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
json_filename = f"TDM_MIMO_{session_timestamp}.mmwave.json"
log_filename = f"TDM_MIMO_{session_timestamp}.log"

try:
    export_config_to_json(config_dict, json_filename)
    print(f"✓ Configuration JSON saved: {json_filename}")
    log_message(log_filename, f"=== TDM-MIMO Session Started ===")
    log_message(log_filename, f"Configuration JSON: {json_filename}")
    log_message(log_filename, f"Record duration: {record_duration} seconds")
    log_message(log_filename, f"Start Frequency: {config_dict['mimo']['profile']['start_freq']} GHz")
    log_message(log_filename, f"Frames per recording: {config_dict['mimo']['frame']['nframes_master']}")
except Exception as e:
    print(f"ERROR: Failed to create JSON config: {e}")

recording_count = 0
try:
    while True:
        recording_count += 1
        log_message(log_filename, f"\n=== Recording {recording_count} Started ===")
        dirName = datetime.now().strftime("TDM_MIMO_%Y%m%d_%H%M%S")
        log_message(log_filename, f"Directory: {dirName}")
        print(f"\n{'=' * 60}")
        print(f"Recording {recording_count}: {dirName}")
        print(f"{'=' * 60}")
        
        try:
            # Step 1: Arm TDA
            print("→ Arming TDA...")
            status = mmwcas.mmw_arming_tda(dirName)
            if status != 0:
                raise Exception(f"Arming TDA failed with status {status}")
            log_message(log_filename, "✓ TDA armed successfully")
            print("✓ TDA armed")
            
            time.sleep(2)
            
            # Step 2: Start frame (triggers all devices in cascade)
            print("→ Starting frame trigger sequence...")
            status = mmwcas.mmw_start_frame()
            if status != 0:
                raise Exception(f"Start frame failed with status {status}")
            log_message(log_filename, "✓ Frame started (Master + Slaves triggered)")
            print("✓ Frame sequence started")

            # Step 3: Wait for recording to complete
            print(f"→ Recording for {record_duration} seconds...")
            time.sleep(record_duration)
            log_message(log_filename, f"✓ Recording completed ({record_duration}s)")
            print("✓ Recording complete")

            # Step 4: Stop frame
            print("→ Stopping frame...")
            status = mmwcas.mmw_stop_frame()
            if status != 0:
                raise Exception(f"Stop frame failed with status {status}")
            log_message(log_filename, "✓ Frame stopped successfully")
            print("✓ Frame stopped")
            
            # Step 5: De-arm TDA
            print("→ De-arming TDA...")
            status = mmwcas.mmw_dearming_tda()
            if status != 0:
                raise Exception(f"Dearming TDA failed with status {status}")
            log_message(log_filename, "✓ TDA de-armed successfully")
            print("✓ TDA de-armed")
            
            time.sleep(2)
            log_message(log_filename, f"✓ Recording {recording_count} completed successfully")
            print(f"\n✓ Recording {recording_count} completed successfully!")
            print(f"  Data saved to: {dirName}")
            
        except Exception as e:
            error_msg = f"Recording {recording_count} failed: {e}"
            log_message(log_filename, f"✗ ERROR: {error_msg}")
            log_message(log_filename, f"*** DO NOT USE FOR ANALYSIS: {dirName} ***")
            print(f"\n✗ {error_msg}")
            print(f"*** Flagged as corrupted: {dirName} ***")
            
            # Cleanup
            print("→ Performing cleanup...")
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
            print("→ Moving to next recording...")
        
        # Small delay between recordings
        time.sleep(1)

except KeyboardInterrupt:
    log_message(log_filename, f"\n=== Session Stopped by user (Ctrl+C) ===")
    log_message(log_filename, f"Total recordings attempted: {recording_count}")
    print("\n\n" + "=" * 60)
    print("SESSION STOPPED BY USER (Ctrl+C)")
    print("=" * 60)
    print(f"Total recordings attempted: {recording_count}")
except Exception as e:
    log_message(log_filename, f"\n=== Unexpected error occurred ===")
    log_message(log_filename, f"Error: {e}")
    log_message(log_filename, f"Total recordings attempted: {recording_count}")
    print(f"\n\n" + "=" * 60)
    print("UNEXPECTED ERROR OCCURRED")
    print("=" * 60)
    print(f"Error: {e}")
    print(f"Total recordings attempted: {recording_count}")
finally:
    # Final cleanup
    print("\n→ Performing final cleanup...")
    try:
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
        log_message(log_filename, "Final cleanup completed")
        print("✓ Final cleanup completed")
    except:
        pass
    print("\nSession ended.")