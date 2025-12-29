import time
import mmwcas
import json
import sys
from datetime import datetime

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

# Configuration structure for JSON export (derived from config_dict and defaults)
full_config = {
    'profileCfg': {
        'profileId': 0,
        'pfVcoSelect': 0x02,
        'startFreqConst': int(77 * 1e9 / 53.6441803),
        'freqSlopeConst': int(15 * 1e3 / 48.2797623),
        'idleTimeConst': int(5 * 100),
        'adcStartTimeConst': int(6 * 100),
        'rampEndTime': int(40 * 100),
        'txOutPowerBackoffCode': 0x0,
        'txPhaseShifter': 0x0,
        'txStartTime': 0,
        'numAdcSamples': 256,
        'digOutSampleRate': 8000,
        'hpfCornerFreq1': 0,
        'hpfCornerFreq2': 0,
        'rxGain': 48,
    },
    'frameCfg': {
        'chirpStartIdx': 0,
        'chirpEndIdx': 11,
        'numFrames': 0,
        'numLoops': 16,
        'numAdcSamples': 512,
        'framePeriodicity': int(100 * 2e5),
    },
    'channelCfg': {
        'rxChannelEn': 0x0F,
        'txChannelEn': 0x07,
    },
    'adcOutCfg': {
        'fmt': {
            'b2AdcBits': 2,
            'b2AdcOutFmt': 1,
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

record_duration = 2
max_retries = 3  # Maximum number of retries per recording attempt

def export_config_to_json(config, filename, num_devices=4):
    """
    Create mmwave.json file from radar configuration dictionary.
    This version is formatted to match mmWave Studio structure exactly.
    """
    print(f"  > Creating JSON configuration file: {filename}")
    
    p_cfg = config['profileCfg']
    f_cfg = config['frameCfg']
    
    # Convert physical values to appropriate units for JSON
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
            "summary": "This is a comments field not passed to device",
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

    for devId in range(num_devices):
        # Table defining which TX is active for each chirp per device
        chirp_tx_table = {0: {11, 10, 9}, 1: {8, 7, 6}, 2: {5, 4, 3}, 3: {2, 1, 0}}
        chirps = []
        for chirpIdx in range(12):
            tx_enable = 0
            # Check if this chirp should be active for current device
            if chirpIdx in chirp_tx_table.get(devId, set()):
                # Sort TX enable bits in order (MSB first)
                tx_map = {val: idx for idx, val in enumerate(sorted(list(chirp_tx_table[devId]), reverse=True))}
                tx_enable = 1 << tx_map[chirpIdx]
            chirps.append({
                "rlChirpCfg_t": {
                    "chirpStartIdx": chirpIdx, "chirpEndIdx": chirpIdx, "profileId": 0,
                    "startFreqVar_MHz": 0.0, "freqSlopeVar_KHz_usec": 0.0,
                    "idleTimeVar_usec": 0.0, "adcStartTimeVar_usec": 0.0,
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
    except IOError as e:
        print(f"ERROR: Failed to save JSON file: {e}", file=sys.stderr)

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

recording_count = 0
try:
    while True:
        recording_count += 1
        print(f"\n=== Recording {recording_count} ===")
        dirName = datetime.now().strftime("Continuous_%Y%m%d_%H%M%S")
        print(f"dirName: {dirName}")
        
        # Create log file name and JSON config file name
        log_filename = f"{dirName}.txt"
        json_filename = f"{dirName}.mmwave.json"
        
        # Write initial log entry
        log_message(log_filename, f"=== Recording {recording_count} Started ===")
        log_message(log_filename, f"Directory: {dirName}")
        log_message(log_filename, f"Record duration: {record_duration} seconds")
        
        # Generate JSON configuration file
        try:
            export_config_to_json(full_config, json_filename)
            log_message(log_filename, f"JSON configuration saved: {json_filename}")
        except Exception as e:
            log_message(log_filename, f"ERROR: Failed to create JSON config: {e}")
        
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
