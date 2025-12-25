import time
import mmwcas
from datetime import datetime
import sys

config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 79,           # GHz
            "frequencySlope": 33,           # MHz/us
            "idleTime": 5,                  # us
            "adcStartTime": 4.21,           # us
            "rampEndTime": 30.06,           # us
            "txStartTime": 0,               # us
            "numAdcSamples": 512,           # samples per chirp
            "adcSamplingFrequency": 20000,  # ksps
            "rxGain": 48,                   # dB
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numFrames": 0,                 # 0 for infinite
            "numLoops": 10,                 # chirps per frame
            "framePeriodicity": 20,         # ms
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}

record_duration = 2
max_retries = 3
max_consecutive_failures = 3  # Exit after this many consecutive failures

def cleanup_hardware(verbose=True):
    """Attempt to cleanup hardware state"""
    cleanup_success = True
    
    # Try to stop frame
    try:
        status = mmwcas.mmw_stop_frame()
        if status != 0 and verbose:
            print(f"  Cleanup: Stop frame returned status {status}")
            cleanup_success = False
    except Exception as e:
        if verbose:
            print(f"  Cleanup: Stop frame exception: {e}")
        cleanup_success = False
    
    # Wait a bit between operations
    time.sleep(0.5)
    
    # Try to dearm TDA
    try:
        status = mmwcas.mmw_dearming_tda()
        if status != 0 and verbose:
            print(f"  Cleanup: Dearming TDA returned status {status}")
            cleanup_success = False
    except Exception as e:
        if verbose:
            print(f"  Cleanup: Dearming TDA exception: {e}")
        cleanup_success = False
    
    return cleanup_success

def full_hardware_reset():
    """Perform extended cleanup with longer delays"""
    print("  Performing extended hardware reset...")
    cleanup_hardware(verbose=False)
    time.sleep(5)  # Longer delay for hardware to fully reset
    print("  Extended reset complete")

def perform_recording(recording_count, dirName):
    """Perform a single recording attempt"""
    try:
        # Arm TDA
        status = mmwcas.mmw_arming_tda(dirName)
        if status != 0:
            raise Exception(f"Arming TDA failed with status {status}")
        
        # Wait for TDA to be ready
        time.sleep(2)
        
        # Start frame
        status = mmwcas.mmw_start_frame()
        if status != 0:
            raise Exception(f"Start frame failed with status {status}")

        # Record for specified duration
        time.sleep(record_duration)

        # Stop frame
        status = mmwcas.mmw_stop_frame()
        if status != 0:
            print(f"  Warning: Stop frame returned status {status}")
        
        # Dearm TDA
        status = mmwcas.mmw_dearming_tda()
        if status != 0:
            print(f"  Warning: Dearming TDA returned status {status}")
        
        # Wait before next recording
        time.sleep(2)
        print(f"Recording {recording_count} completed successfully")
        return True
        
    except Exception as e:
        raise e

# Initialize hardware
print("Initializing mmWave radar system...")
status = mmwcas.mmw_set_config(config_dict)
if status != 0:
    print(f"Configuration failed with status {status}")
    sys.exit(1)

status = mmwcas.mmw_init()
if status != 0:
    print(f"Initialization failed with status {status}")
    sys.exit(1)

time.sleep(2)
print("Initialization complete. Starting continuous recording...\n")

recording_count = 0
consecutive_failures = 0

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
                success = perform_recording(recording_count, dirName)
                if success:
                    consecutive_failures = 0  # Reset failure counter on success
                
            except Exception as e:
                retry_count += 1
                print(f"Recording {recording_count} failed on attempt {retry_count}/{max_retries}")
                print(f"Error: {e}")
                
                # Cleanup after failure
                cleanup_success = cleanup_hardware()
                
                if retry_count < max_retries:
                    # Determine wait time based on failure severity
                    if not cleanup_success or retry_count > 1:
                        # If cleanup failed or we're on later retries, wait longer
                        wait_time = 5 + (retry_count * 2)
                        print(f"  Cleanup had issues. Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
                        
                        # Perform extended reset on second retry
                        if retry_count == 2:
                            full_hardware_reset()
                    else:
                        print(f"  Waiting 3 seconds before retry...")
                        time.sleep(3)
                    
                    # Generate new directory name for retry
                    dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
                    print(f"  Retrying with new dirName: {dirName}")
                else:
                    print(f"Recording {recording_count} failed after {max_retries} attempts.")
                    consecutive_failures += 1
        
        # Check if we've had too many consecutive failures
        if not success:
            if consecutive_failures >= max_consecutive_failures:
                print(f"\n!!! {max_consecutive_failures} consecutive recordings failed !!!")
                print("System may need manual reset. Exiting...")
                break
            else:
                print(f"Moving to next recording (consecutive failures: {consecutive_failures}/{max_consecutive_failures})")
                # Extra delay and reset after a failed recording
                full_hardware_reset()
        
        # Small delay between recordings
        time.sleep(1)

except KeyboardInterrupt:
    print("\n\n=== Stopped by user (Ctrl+C) ===")
    print(f"Total recordings attempted: {recording_count}")
    print(f"Consecutive failures before stop: {consecutive_failures}")
except Exception as e:
    print(f"\n\n=== Unexpected error occurred ===")
    print(f"Error: {e}")
    print(f"Total recordings attempted: {recording_count}")
finally:
    # Final cleanup
    print("\nPerforming final cleanup...")
    cleanup_hardware()
    print("Cleanup complete. Exiting.")