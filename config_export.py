import json
import sys
from datetime import datetime

def export_config_to_json(config_dict, filename, num_devices=4):
    """
    Create mmwave.json file from radar configuration dictionary.
    This version matches the exact structure from mmWave Studio.
    
    Args:
        config_dict: Dictionary containing MIMO configuration with profile, frame, and channel settings
        filename: Output JSON filename
        num_devices: Number of devices in cascade (default: 4)
    """
    print(f"  > Creating JSON configuration file: {filename}")
    
    # Extract configuration from config_dict
    profile = config_dict["mimo"]["profile"]
    frame = config_dict["mimo"]["frame"]
    channel = config_dict["mimo"]["channel"]
    
    # Profile values
    startFreq_GHz = profile["start_freq"]
    freqSlope_MHz_usec = profile["slope"]
    idleTime_usec = profile["idle_time"]
    adcStartTime_usec = profile["adc_start_time"]
    rampEndTime_usec = profile["ramp_end_time"]
    txStartTime_usec = profile.get("txStartTimeUSec", 0)
    numAdcSamples = profile["adc_samples"]
    digOutSampleRate = profile["sample_freq"]
    hpfCornerFreq1 = profile["hpfCornerFreq1"]
    hpfCornerFreq2 = profile["hpfCornerFreq2"]
    rxGain = profile["rx_gain"]
    profileId = profile["id"]
    
    # Frame values
    numLoops = frame["nchirp_loops"]
    numFrames = frame["nframes_master"]
    framePeriodicity_msec = frame["Inter_Frame_Interval"]
    
    # Channel values
    rxChannelEn = channel["rxChannelEn"]
    txChannelEn = channel["txChannelEn"]
    
    # ADC and data format settings
    adcBits = 2  # 16-bit ADC
    adcOutFmt = 1  # Complex values
    iqSwapSel = 0  # I first
    chInterleave = 0  # Interleaved mode
    
    # Datapath settings
    intfSel = 0  # CSI2 interface
    transferFmtPkt0 = 1  # ADC data only
    transferFmtPkt1 = 0  # Suppress packet 1
    laneClkCfg = 1  # DDR Clock
    dataRate_Mbps = 600
    
    # LDO and power settings
    ldoBypassEnable = 3
    ioSupplyIndicator = 0
    supplyMonIrDrop = 0
    lpAdcMode = 0
    miscCtl = 1
    
    # CSI2 settings
    lanePosPolSel = 0x35421
    lineStartEndDis = 0

    json_output = {
        "configGenerator": {
            "createdBy": "mmWavel CLI Python Script",
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
                    "chirpStartIdx": chirpIdx,
                    "chirpEndIdx": chirpIdx,
                    "profileId": profileId,
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
                "waveformType": "legacyFrameChirp",
                "MIMOScheme": "TDM",
                "rlCalibrationDataFile": "",
                "rlChanCfg_t": {
                    "rxChannelEn": f"0x{rxChannelEn:X}",
                    "txChannelEn": f"0x{txChannelEn:X}",
                    "cascading": 1 if devId == 0 else 2,
                    "cascadingPinoutCfg": "0x0"
                },
                "rlAdcOutCfg_t": {
                    "fmt": {
                        "b2AdcBits": adcBits,
                        "b8FullScaleReducFctr": 0,
                        "b2AdcOutFmt": adcOutFmt
                    }
                },
                "rlLowPowerModeCfg_t": {
                    "lpAdcMode": lpAdcMode
                },
                "rlProfiles": [{
                    "rlProfileCfg_t": {
                        "profileId": profileId,
                        "pfVcoSelect": "0x0",
                        "pfCalLutUpdate": "0x0",
                        "startFreqConst_GHz": startFreq_GHz,
                        "idleTimeConst_usec": idleTime_usec,
                        "adcStartTimeConst_usec": adcStartTime_usec,
                        "rampEndTime_usec": rampEndTime_usec,
                        "txOutPowerBackoffCode": "0x0",
                        "txPhaseShifter": "0x0",
                        "freqSlopeConst_MHz_usec": freqSlope_MHz_usec,
                        "txStartTime_usec": txStartTime_usec,
                        "numAdcSamples": numAdcSamples,
                        "digOutSampleRate": float(digOutSampleRate),
                        "hpfCornerFreq1": hpfCornerFreq1,
                        "hpfCornerFreq2": hpfCornerFreq2,
                        "rxGain_dB": f"0x{rxGain:X}"
                    }
                }],
                "rlChirps": chirps,
                "rlRfInitCalConf_t": {
                    "calibEnMask": "0x1FF0"
                },
                "rlFrameCfg_t": {
                    "chirpEndIdx": 11,
                    "chirpStartIdx": 0,
                    "numLoops": numLoops,
                    "numFrames": numFrames,
                    "framePeriodicity_msec": float(framePeriodicity_msec),
                    "triggerSelect": 1 if devId == 0 else 2,
                    "frameTriggerDelay": 0.0
                },
                "rlBpmChirps": [],
                "rlRfMiscConf_t": {
                    "miscCtl": f"{miscCtl}"
                },
                "rlRfPhaseShiftCfgs": [],
                "rlRfProgFiltConfs": [],
                "rlRfLdoBypassCfg_t": {
                    "ldoBypassEnable": ldoBypassEnable,
                    "supplyMonIrDrop": supplyMonIrDrop,
                    "ioSupplyIndicator": ioSupplyIndicator
                },
                "rlLoopbackBursts": [],
                "rlDynChirpCfgs": [],
                "rlDynPerChirpPhShftCfgs": []
            },
            "rawDataCaptureConfig": {
                "rlDevDataFmtCfg_t": {
                    "iqSwapSel": iqSwapSel,
                    "chInterleave": chInterleave
                },
                "rlDevDataPathCfg_t": {
                    "intfSel": intfSel,
                    "transferFmtPkt0": f"0x{transferFmtPkt0:X}",
                    "transferFmtPkt1": f"0x{transferFmtPkt1:X}",
                    "cqConfig": 0,
                    "cq0TransSize": 0,
                    "cq1TransSize": 0,
                    "cq2TransSize": 0
                },
                "rlDevDataPathClkCfg_t": {
                    "laneClkCfg": laneClkCfg,
                    "dataRate_Mbps": dataRate_Mbps
                },
                "rlDevCsi2Cfg_t": {
                    "lanePosPolSel": f"0x{lanePosPolSel:X}",
                    "lineStartEndDis": lineStartEndDis
                }
            },
            "monitoringConfig": {}
        }
        json_output["mmWaveDevices"].append(device_config)

    # Add processing chain config
    json_output["processingChainConfig"] = {
        "detectionChain": {
            "name": "TI_GenericChain",
            "detectionLoss": 1,
            "systemLoss": 1,
            "implementationMargin": 2,
            "detectionSNR": 12,
            "theoreticalRxAntennaGain": 9,
            "theoreticalTxAntennaGain": 9
        }
    }

    try:
        with open(filename, 'w') as f:
            json.dump(json_output, f, indent=2)
        print(f"  > Successfully saved configuration to {filename}")
    except IOError as e:
        print(f"ERROR: Failed to save JSON file: {e}", file=sys.stderr)