#!/usr/bin/env python3
"""
Generate mmWave Studio-compatible .mmwave.json and .setup.json
from a simple .toml configuration file (used in mmwave Linux CLI)
Author: Rogers Dwiputra (adapted by ChatGPT)
"""

import tomllib
import json
import os
import sys
import time
from datetime import datetime


def generate_mmwave_json(toml_path: str, output_dir: str, board_ip="192.168.33.180"):
    # Load TOML
    with open(toml_path, "rb") as f:
        toml_data = tomllib.load(f)

    base_name = os.path.splitext(os.path.basename(toml_path))[0]
    timestamp = int(time.time())
    iso_time = datetime.now().isoformat()

    # Extract configuration from TOML
    mimo = toml_data.get("mimo", {})
    profile = mimo.get("profile", {})
    frame = mimo.get("frame", {})
    channel = mimo.get("channel", {})

    # Construct mmWaveStudio-compatible JSON structure
    mmwave_json = {
        "configGenerator": {
            "createdBy": "mmwave-cli-linux",
            "createdOn": iso_time,
            "isConfigIntermediate": 1
        },
        "currentVersion": {
            "jsonCfgVersion": {"major": 0, "minor": 4, "patch": 0},
            "DFPVersion": {"major": 2, "minor": 2, "patch": 0},
            "SDKVersion": {"major": 3, "minor": 3, "patch": 0},
            "mmwavelinkVersion": {"major": 2, "minor": 2, "patch": 0}
        },
        "regulatoryRestrictions": {
            "frequencyRangeBegin_GHz": 76,
            "frequencyRangeEnd_GHz": 81,
            "maxBandwidthAllowed_MHz": 4000,
            "maxTransmitPowerAllowed_dBm": 12
        },
        "systemConfig": {
            "summary": "Auto-generated from Linux mmwave capture",
            "sceneParameters": {
                "ambientTemperature_degC": 25,
                "maxDetectableRange_m": 80,
                "rangeResolution_cm": 30,
                "maxVelocity_kmph": 6.49,
                "velocityResolution_kmph": 0.4,
                "measurementRate": 10,
                "typicalDetectedObjectRCS": 1.0
            }
        },
        "mmWaveDevices": [
            {
                "mmWaveDeviceId": 0,
                "rfConfig": {
                    "waveformType": "legacyFrameChirp",
                    "MIMOScheme": "TDM",
                    "rlChanCfg_t": {
                        "rxChannelEn": f"0x{channel.get('rxChannelEn',15):X}",
                        "txChannelEn": f"0x{channel.get('txChannelEn',7):X}",
                        "cascading": 1,
                        "cascadingPinoutCfg": "0x0"
                    },
                    "rlProfiles": [
                        {
                            "rlProfileCfg_t": {
                                "profileId": profile.get("id", 0),
                                "startFreqConst_GHz": profile.get("startFrequency", 77),
                                "idleTimeConst_usec": profile.get("idleTime", 5),
                                "adcStartTimeConst_usec": profile.get("adcStartTime", 6),
                                "rampEndTime_usec": profile.get("rampEndTime", 40),
                                "freqSlopeConst_MHz_usec": profile.get("frequencySlope", 15.0148),
                                "numAdcSamples": profile.get("numAdcSamples", 256),
                                "rxGain_dB": profile.get("rxGain", 48)
                            }
                        }
                    ],
                    "rlFrameCfg_t": {
                        "numLoops": frame.get("numLoops", 16),
                        "numFrames": frame.get("numFrames", 0),
                        "framePeriodicity_msec": frame.get("framePeriodicity", 100.0),
                        "triggerSelect": 1
                    }
                },
                "rawDataCaptureConfig": {
                    "rlDevDataFmtCfg_t": {"iqSwapSel": 0, "chInterleave": 0},
                    "rlDevDataPathCfg_t": {
                        "intfSel": 0,
                        "transferFmtPkt0": "0x1",
                        "transferFmtPkt1": "0x0"
                    }
                }
            }
        ],
        "processingChainConfig": {
            "detectionChain": {
                "name": "SimplifiedChain",
                "detectionLoss": 1,
                "systemLoss": 1,
                "implementationMargin": 2,
                "detectionSNR": 12
            }
        }
    }

    # Prepare setup.json metadata
    setup_json = {
        "capture_directory": os.path.basename(output_dir),
        "board_ip": board_ip,
        "firmware_image": "xwr22xx_metaImage.bin",
        "config_file": os.path.basename(toml_path),
        "generated_at": iso_time,
        "unix_timestamp": timestamp,
        "note": "mmWave Studio compatible metadata"
    }

    # Save both JSONs
    os.makedirs(output_dir, exist_ok=True)
    mmwave_path = os.path.join(output_dir, f"{base_name}.mmwave.json")
    setup_path = os.path.join(output_dir, f"{base_name}.setup.json")

    with open(mmwave_path, "w", encoding="utf-8") as f:
        json.dump(mmwave_json, f, indent=2)
    with open(setup_path, "w", encoding="utf-8") as f:
        json.dump(setup_json, f, indent=2)

    print(f"[OK] Generated mmWaveStudio-compatible JSONs:\n  {mmwave_path}\n  {setup_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 generate_mmwave_json_compatible.py <config.toml> <output_dir> [board_ip]")
        sys.exit(1)

    toml_path = sys.argv[1]
    output_dir = sys.argv[2]
    board_ip = sys.argv[3] if len(sys.argv) >= 4 else "192.168.33.180"

    generate_mmwave_json(toml_path, output_dir, board_ip)
