import time
import mmwcas
import json
import sys
import os
from datetime import datetime

config_dict = {
    "mimo": {
        "profile": {
            "id": 0,
            "startFrequency": 77,           # Chirp start frequency in GHz
            "frequencySlope": 25,           # Frequency slope in MHz/us
            "idleTime": 7,                  # Chrip Idle time in us
            "adcStartTime": 4.35,              # ADC start time in us
            "numAdcSamples": 512,           # Number of ADC samples per chirp
            "adcSamplingFrequency": 8000,  # ADC sampling frequency in ksps
            "rampEndTime": 68.97,              # Chirp ramp end time in us
            "rxGain": 48,                   # dB
            "txStartTime": 0,               # TX starttime in us
            "hpfCornerFreq1": 0,            # 0: 175kHz
            "hpfCornerFreq2": 0,            # 0: 350kHz
        },
        "frame": {
            "numLoops": 10,                 # Number of chirp loop per frame
            "numFrames": 0,                 # Number of frames to record (0=infinite)
            "framePeriodicity": 10,         # Frame periodicity in ms (Inter_Frame_Interval)
        },
        "channel": {
            "rxChannelEn": 0x0F,            # Enable all 4 RX channels
            "txChannelEn": 0x07,            # Enable all 3 TX channels
        }
    }
}

record_duration = 2
max_retries = 3

# PostProc directory where data will be transferred
postproc_dir = "/Users/mac/Documents/PHD-Muroran/PostProc"


def build_full_config_from_dict(config_dict):
    """Build full configuration from config_dict with proper conversions"""
    profile = config_dict["mimo"]["profile"]
    frame = config_dict["mimo"]["frame"]
    channel = config_dict["mimo"]["channel"]
    
    # Convert GHz to device units (1 LSB = 53.6441803 Hz)
    startFreqConst = int(profile["startFrequency"] * 1e9 / 53.6441803)
    
    # Convert MHz/us to device units (1 LSB = 48.2797623 kHz/us)
    freqSlopeConst = int(profile["frequencySlope"] * 1e3 / 48.2797623)
    
    # Convert us to device units (1 LSB = 10 ns)
    idleTimeConst = int(profile["idleTime"] * 100)
    adcStartTimeConst = int(profile["adcStartTime"] * 100)
    rampEndTime = int(profile["rampEndTime"] * 100)
    txStartTime = int(profile["txStartTime"] * 100)
    
    # Convert ms to device units (1 LSB = 5 ns)
    framePeriodicity = int(frame["framePeriodicity"] * 2e5)
    
    full_config = {
        'profileCfg': {
            'profileId': profile["id"],
            'pfVcoSelect': 0x02,
            'startFreqConst': startFreqConst,
            'freqSlopeConst': freqSlopeConst,
            'idleTimeConst': idleTimeConst,
            'adcStartTimeConst': adcStartTimeConst,
            'rampEndTime': rampEndTime,
            'txOutPowerBackoffCode': 0x0,
            'txPhaseShifter': 0x0,
            'txStartTime': txStartTime,
            'numAdcSamples': profile["numAdcSamples"],
            'digOutSampleRate': profile["adcSamplingFrequency"],
            'hpfCornerFreq1': profile["hpfCornerFreq1"],
            'hpfCornerFreq2': profile["hpfCornerFreq2"],
            'rxGain': profile["rxGain"],
        },
        'frameCfg': {
            'chirpStartIdx': 0,
            'chirpEndIdx': 11,
            'numFrames': frame["numFrames"],
            'numLoops': frame["numLoops"],
            'numAdcSamples': 2 * profile["numAdcSamples"],  # Complex I/Q
            'framePeriodicity': framePeriodicity,
        },
        'channelCfg': {
            'rxChannelEn': channel["rxChannelEn"],
            'txChannelEn': channel["txChannelEn"],
        },
        'adcOutCfg': {
            'fmt': {
                'b2AdcBits': 2,          # 16-bit
                'b2AdcOutFmt': 1,        # Complex
                'b8FullScaleReducFctr': 0,
            }
        },
        'dataFmtCfg': {
            'iqSwapSel': 0,
            'chInterleave': 0,
        },
        'lpmCfg': {
            'lpAdcMode': 0,
        },
        'miscCfg': {
            'miscCtl': 1,
        },
        'ldoCfg': {
            'ldoBypassEnable': 3,
            'ioSupplyIndicator': 0,
            'supplyMonIrDrop': 0,
        },
        'datapathCfg': {
            'intfSel': 0,
            'transferFmtPkt0': 1,
            'transferFmtPkt1': 0,
        },
        'datapathClkCfg': {
            'laneClkCfg': 1,
            'dataRate': 1,  # 600Mbps
        },
        'csi2LaneCfg': {
            'lanePosPolSel': 0x35421,
            'lineStartEndDis': 0,
        }
    }
    
    return full_config


def export_config_to_json(config, filename, num_devices=4):
    """
    Create mmwave.json file from radar configuration dictionary.
    This version is formatted to match mmWave Studio structure exactly.
    """
    print(f"  > Creating JSON configuration file: {filename}")
    
    p_cfg = config['profileCfg']
    f_cfg = config['frameCfg']
    
    # Convert device units back to physical values for JSON
    startFreq_GHz = (p_cfg['startFreqConst'] * 53.6441803) / 1e9
    freqSlope_MHz_usec = (p_cfg['freqSlopeConst'] * 48.2797623) / 1000.0
    idleTime_usec = p_cfg['idleTimeConst'] * 0.01
    adcStartTime_usec = p_cfg['adcStartTimeConst'] * 0.01
    rampEndTime_usec = p_cfg['rampEndTime'] * 0.01
    txStartTime_usec = p_cfg['txStartTime'] * 0.01
    framePeriodicity_msec = (f_cfg['framePeriodicity'] * 5.0) / 1e6
    
    # Determine data rate based on config value
    data_rate_map = {0: 150, 1: 300, 2: 450, 3: 600}
    dataRate_Mbps = data_rate_map.get(config['datapathClkCfg']['dataRate'], 600)

    json_output = {
        "configGenerator": {
            "createdBy": "mmwave-cli-python",
            "createdOn": datetime.now().astimezone().isoformat(),
            "isConfigIntermediate": 1
        },
        "currentVersion": {
            "jsonCfgVersion": {
                "major": 0,
                "minor": 4,
                "patch": 0
            },
            "DFPVersion": {
                "major": 2,
                "minor": 2,
                "patch": 0
            },
            "SDKVersion": {
                "major": 3,
                "minor": 3,
                "patch": 0
            },
            "mmwavelinkVersion": {
                "major": 2,
                "minor": 2,
                "patch": 0
            }
        },
        "lastBackwardCompatibleVersion": {
            "DFPVersion": {
                "major": 2,
                "minor": 1,
                "patch": 0
            },
            "SDKVersion": {
                "major": 3,
                "minor": 0,
                "patch": 0
            },
            "mmwavelinkVersion": {
                "major": 2,
                "minor": 1,
                "patch": 0
            }
        },
        "regulatoryRestrictions": {
            "frequencyRangeBegin_GHz": 77,
            "frequencyRangeEnd_GHz": 81,
            "maxBandwidthAllowed_MHz": 4000,
            "maxTransmitPowerAllowed_dBm": 12
        },
        "systemConfig": {
            "summary": "MIMO Cascade Configuration",
            "sceneParameters": {
                "ambientTemperature_degC": 20,
                "maxDetectableRange_m": 10,
                "rangeResolution_cm": 5,
                "maxVelocity_kmph": 26,
                "velocityResolution_kmph": 2,
                "measurementRate": 10,
                "typicalDetectedObjectRCS": 1.0
            }
        },
        "mmWaveDevices": []
    }

    # TDM-MIMO chirp TX table: which TX fires for each chirp per device
    chirp_tx_table = {
        0: {11: 0, 10: 1, 9: 2},   # Device 0 (Master): chirps 11,10,9 → TX0,1,2
        1: {8: 0, 7: 1, 6: 2},     # Device 1 (Slave1): chirps 8,7,6 → TX0,1,2
        2: {5: 0, 4: 1, 3: 2},     # Device 2 (Slave2): chirps 5,4,3 → TX0,1,2
        3: {2: 0, 1: 1, 0: 2}      # Device 3 (Slave3): chirps 2,1,0 → TX0,1,2
    }

    for devId in range(num_devices):
        chirps = []
        for chirpIdx in range(12):
            # Check if this chirp should be active for current device
            if chirpIdx in chirp_tx_table[devId]:
                tx_idx = chirp_tx_table[devId][chirpIdx]
                tx_enable = 1 << tx_idx  # Enable specific TX
            else:
                tx_enable = 0  # No TX enabled for this chirp
                
            chirps.append({
                "rlChirpCfg_t": {
                    "chirpStartIdx": chirpIdx,
                    "chirpEndIdx": chirpIdx,
                    "profileId": 0,
                    "startFreqVar_MHz": 0.0,
                    "freqSlopeVar_KHz_usec": 0.0,
                    "idleTimeVar_usec": 0.0,
                    "adcStartTimeVar_usec": 0.0,
                    "txEnable": f"0x{tx_enable:X}"
                }
            })

        device_config = {
            "mmWaveDeviceId": devId,
            "rfConfig": {
                "rlChanCfg_t": {
                    "rxChannelEn": f"0x{config['channelCfg']['rxChannelEn']:X}",
                    "txChannelEn": f"0x{config['channelCfg']['txChannelEn']:X}",
                    "cascading": 1 if devId == 0 else 2,
                    "cascadingPinoutCfg": "0x0"
                },
                "rlAdcOutCfg_t": {
                    "fmt": config['adcOutCfg']['fmt']
                },
                "rlLowPowerModeCfg_t": config['lpmCfg'],
                "rlProfiles": [{
                    "rlProfileCfg_t": {
                        "profileId": p_cfg['profileId'],
                        "pfVcoSelect": f"0x{p_cfg['pfVcoSelect']:X}",
                        "startFreqConst_GHz": startFreq_GHz,
                        "idleTimeConst_usec": idleTime_usec,
                        "adcStartTimeConst_usec": adcStartTime_usec,
                        "rampEndTime_usec": rampEndTime_usec,
                        "txOutPowerBackoffCode": f"0x{p_cfg['txOutPowerBackoffCode']:X}",
                        "txPhaseShifter": f"0x{p_cfg['txPhaseShifter']:X}",
                        "freqSlopeConst_MHz_usec": freqSlope_MHz_usec,
                        "txStartTime_usec": txStartTime_usec,
                        "numAdcSamples": p_cfg['numAdcSamples'],
                        "digOutSampleRate": float(p_cfg['digOutSampleRate']),
                        "hpfCornerFreq1": p_cfg['hpfCornerFreq1'],
                        "hpfCornerFreq2": p_cfg['hpfCornerFreq2'],
                        "rxGain_dB": f"0x{p_cfg['rxGain']:X}"
                    }
                }],
                "rlChirps": chirps,
                "rlRfInitCalConf_t": {
                    "calibEnMask": "0x1FF0"
                },
                "rlFrameCfg_t": {
                    "chirpEndIdx": f_cfg['chirpEndIdx'],
                    "chirpStartIdx": f_cfg['chirpStartIdx'],
                    "numLoops": f_cfg['numLoops'],
                    "numFrames": f_cfg['numFrames'],
                    "framePeriodicity_msec": framePeriodicity_msec,
                    "triggerSelect": 1 if devId == 0 else 2,
                    "frameTriggerDelay": 0.0
                },
                "rlRfMiscConf_t": {
                    "miscCtl": f"{config['miscCfg']['miscCtl']}"
                },
                "rlRfLdoBypassCfg_t": config['ldoCfg']
            },
            "rawDataCaptureConfig": {
                "rlDevDataFmtCfg_t": {
                    "iqSwapSel": config['dataFmtCfg']['iqSwapSel'],
                    "chInterleave": config['dataFmtCfg']['chInterleave']
                },
                "rlDevDataPathCfg_t": {
                    "intfSel": config['datapathCfg']['intfSel'],
                    "transferFmtPkt0": f"0x{config['datapathCfg']['transferFmtPkt0']:X}",
                    "transferFmtPkt1": f"0x{config['datapathCfg']['transferFmtPkt1']:X}",
                    "cqConfig": 0,
                    "cq0TransSize": 0,
                    "cq1TransSize": 0,
                    "cq2TransSize": 0
                },
                "rlDevDataPathClkCfg_t": {
                    "laneClkCfg": config['datapathClkCfg']['laneClkCfg'],
                    "dataRate_Mbps": dataRate_Mbps
                },
                "rlDevCsi2Cfg_t": {
                    "lanePosPolSel": f"0x{config['csi2LaneCfg']['lanePosPolSel']:X}",
                    "lineStartEndDis": config['csi2LaneCfg']['lineStartEndDis']
                }
            }
        }
        json_output["mmWaveDevices"].append(device_config)

    try:
        with open(filename, 'w') as f:
            json.dump(json_output, f, indent=2)
        print(f"  > Successfully saved configuration to {filename}")
        return True
    except IOError as e:
        print(f"ERROR: Failed to save JSON file: {e}", file=sys.stderr)
        return False


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


# ==================== MAIN SCRIPT ====================

# Build full config from config_dict
full_config = build_full_config_from_dict(config_dict)

# Create session timestamp for log file (ONE log file for entire session)
session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
master_log_filename = os.path.join(postproc_dir, f"ContinuousCapture_{session_timestamp}.log")

# Generate ONE JSON configuration file for this session
master_json_filename = os.path.join(postproc_dir, f"radar_config_{session_timestamp}.mmwave.json")

log_message(master_log_filename, "=" * 80)
log_message(master_log_filename, "MIMO RADAR CONTINUOUS CAPTURE SESSION STARTED")
log_message(master_log_filename, "=" * 80)
log_message(master_log_filename, f"Session ID: {session_timestamp}")
log_message(master_log_filename, f"Record duration per capture: {record_duration} seconds")
log_message(master_log_filename, f"Max retries per capture: {max_retries}")
log_message(master_log_filename, f"Configuration: {json.dumps(config_dict, indent=2)}")

# Generate master JSON configuration ONCE
log_message(master_log_filename, "\n--- Generating Master JSON Configuration ---")
if export_config_to_json(full_config, master_json_filename):
    log_message(master_log_filename, f"Master JSON saved: {master_json_filename}")
else:
    log_message(master_log_filename, "ERROR: Failed to create master JSON configuration!")
    sys.exit(1)

# Initialize the system
log_message(master_log_filename, "\n--- Initializing Radar System ---")
status = mmwcas.mmw_set_config(config_dict)
if status != 0:
    log_message(master_log_filename, f"ERROR: mmw_set_config failed with status {status}")
    raise ValueError(f"Configuration failed: {status}")
log_message(master_log_filename, "Configuration set successfully")

status = mmwcas.mmw_init()
if status != 0:
    log_message(master_log_filename, f"ERROR: mmw_init failed with status {status}")
    raise ValueError(f"Initialization failed: {status}")
log_message(master_log_filename, "Radar initialized successfully")
time.sleep(2)

recording_count = 0
successful_recordings = 0
failed_recordings = 0

try:
    while True:
        recording_count += 1
        log_message(master_log_filename, "\n" + "=" * 80)
        log_message(master_log_filename, f"RECORDING #{recording_count} STARTED")
        log_message(master_log_filename, "=" * 80)
        
        dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
        log_message(master_log_filename, f"Capture directory: {dirName}")
        
        # Copy master JSON to capture directory for MATLAB processing
        capture_json_path = os.path.join(postproc_dir, dirName, f"{dirName}.mmwave.json")
        
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                log_message(master_log_filename, f"Attempt {retry_count + 1}/{max_retries}")
                
                status = mmwcas.mmw_arming_tda(dirName)
                if status != 0:
                    raise Exception(f"Arming TDA failed with status {status}")
                log_message(master_log_filename, "✓ TDA armed successfully")
                
                time.sleep(2)
                
                status = mmwcas.mmw_start_frame()
                if status != 0:
                    raise Exception(f"Start frame failed with status {status}")
                log_message(master_log_filename, "✓ Frame started successfully")

                log_message(master_log_filename, f"Recording for {record_duration} seconds...")
                time.sleep(record_duration)
                log_message(master_log_filename, f"✓ Recording completed ({record_duration}s)")

                status = mmwcas.mmw_stop_frame()
                if status != 0:
                    log_message(master_log_filename, f"⚠ Warning: Stop frame returned status {status}")
                else:
                    log_message(master_log_filename, "✓ Frame stopped successfully")
                
                status = mmwcas.mmw_dearming_tda()
                if status != 0:
                    log_message(master_log_filename, f"⚠ Warning: Dearming TDA returned status {status}")
                else:
                    log_message(master_log_filename, "✓ TDA de-armed successfully")
                
                # Copy JSON to capture directory (will be created after data transfer)
                # Note: This assumes the directory will be created on TDA and transferred
                log_message(master_log_filename, f"Note: Use master JSON at {master_json_filename} for MATLAB processing")
                
                time.sleep(2)
                log_message(master_log_filename, f"✓✓✓ Recording #{recording_count} COMPLETED SUCCESSFULLY ✓✓✓")
                successful_recordings += 1
                success = True
                
            except Exception as e:
                retry_count += 1
                error_msg = f"Recording #{recording_count} failed on attempt {retry_count}/{max_retries}: {e}"
                log_message(master_log_filename, f"✗✗✗ ERROR: {error_msg}")
                
                # Cleanup before retry
                try:
                    mmwcas.mmw_stop_frame()
                    log_message(master_log_filename, "Cleanup: Frame stopped")
                except:
                    pass
                
                try:
                    mmwcas.mmw_dearming_tda()
                    log_message(master_log_filename, "Cleanup: TDA de-armed")
                except:
                    pass
                
                if retry_count < max_retries:
                    log_message(master_log_filename, f"Waiting 3 seconds before retry...")
                    time.sleep(3)
                    # Generate new directory name for retry
                    dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
                    log_message(master_log_filename, f"Retrying with new dirName: {dirName}")
                else:
                    log_message(master_log_filename, f"✗✗✗ Recording #{recording_count} FAILED after {max_retries} attempts")
                    failed_recordings += 1
        
        # Small delay between recordings
        time.sleep(1)

except KeyboardInterrupt:
    log_message(master_log_filename, "\n" + "=" * 80)
    log_message(master_log_filename, "SESSION STOPPED BY USER (Ctrl+C)")
    log_message(master_log_filename, "=" * 80)
except Exception as e:
    log_message(master_log_filename, "\n" + "=" * 80)
    log_message(master_log_filename, f"SESSION STOPPED: Unexpected error occurred")
    log_message(master_log_filename, f"Error: {e}")
    log_message(master_log_filename, "=" * 80)
finally:
    # Final cleanup
    try:
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
        log_message(master_log_filename, "Final cleanup completed")
    except:
        pass
    
    # Session summary
    log_message(master_log_filename, "\n" + "=" * 80)
    log_message(master_log_filename, "SESSION SUMMARY")
    log_message(master_log_filename, "=" * 80)
    log_message(master_log_filename, f"Total recordings attempted: {recording_count}")
    log_message(master_log_filename, f"Successful recordings: {successful_recordings}")
    log_message(master_log_filename, f"Failed recordings: {failed_recordings}")
    log_message(master_log_filename, f"Success rate: {(successful_recordings/recording_count*100) if recording_count > 0 else 0:.1f}%")
    log_message(master_log_filename, f"Master JSON configuration: {master_json_filename}")
    log_message(master_log_filename, f"Session log file: {master_log_filename}")
    log_message(master_log_filename, "=" * 80)
    
    print(f"\n{'='*80}")
    print(f"Session ended. Check log file: {master_log_filename}")
    print(f"Use JSON config: {master_json_filename}")
    print(f"{'='*80}")