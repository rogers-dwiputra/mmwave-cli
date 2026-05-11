# CLAUDE.md — mmwave-cli

## Project Overview

Automated pipeline for **Bridge Structural Health Monitoring** using a TIDEP-01012 MIMO Cascade Radar (77 GHz, 4-chip AWR2243 cascade). The system continuously captures radar data, transfers it to a processing host, runs edge processing, extracts structural vibration metrics via Permanent Scatterer (PS) interferometry, and transmits results to the cloud via LoRaWAN.

**Research context:** PhD project at IMRSL, Muroran Institute of Technology.  
**Goal:** Detect bridge modal frequencies and displacement via sub-mm radar interferometry, transmit via LoRaWAN (Wio-E5 → TTN) for remote dashboard monitoring.

**Status:** Full pipeline operational end-to-end (capture → edge processing → LoRa → TTN). Validated in lab (static ceiling test). Next: vibrating table validation, then bridge deployment.

---

## Hardware

| Component | Details |
|-----------|---------|
| Radar | TIDEP-01012 — 4× AWR2243, 12 TX × 16 RX virtual, 77 GHz |
| DSP board | TDA2XX (mmWave DSP EVM) |
| TDA IP | `192.168.33.180` (static, over Ethernet) |
| TDA data storage | `/mnt/ssd/<capture_dir>/` |
| Processing host | Raspberry Pi 5 (ARM Cortex-A76), hostname `imrslpi5-02`, user `imrsl` |
| LoRaWAN modem | Wio-E5 Development Kit (SeeedStudio) — `/dev/ttyUSB0`, 9600 baud, CP2102N |
| LoRaWAN network | The Things Stack (TTN) — tenant `imrsl`, app `iosar-imrsl`, device `gb-sar-01` |

**Key radar parameters (mimo.py config):**
- `framePeriodicity = 100 ms` → frame rate = 10 Hz, `dt = 0.1 s`
- `numAdcSamples = 256`, `adcSamplingFrequency = 8000 ksps`
- `frequencySlope = 79.0327 MHz/μs`, `rampEndTime = 40 μs`
- `numLoops = 16` chirp loops per frame
- λ ≈ 3.896 mm at 77 GHz

---

## Repository Structure

```
mmwave-cli/                         ← this repo (runs on Raspberry Pi ~/mmwave-cli/)
├── mimo.py                         ← radar control: configure, arm, capture, stop
├── mimo.c / mimo.h                 ← C extension source (mmwcas Python module)
├── mmwcas.pyx / mmwcas.pyi         ← Cython wrapper for mmwcas C extension
├── setup.py                        ← build mmwcas extension
├── pipeline.py                     ← automated 5-step pipeline (main entry point)
├── lora_sender.py                  ← LoRaWAN uplink via Wio-E5 AT commands (Step 5)
├── utility.py                      ← check_captured_files(), export_config_to_json()
├── mmwave_json_files/              ← generated .mmwave.json config files (per capture)
├── config/                         ← TOML radar config files (reference)
└── ti/                             ← TI SDK headers and firmware

~/IoSAR-EdgeProcessing/             ← edge processing (separate repo, OneDrive-synced)
├── mimo_processing.py              ← range FFT → Doppler FFT → beamforming → SLC image
├── ps_monitoring.py                ← PS selection → phase extraction → FFT → modal frequencies
├── ps_map.json                     ← learned PS candidate map (auto-generated, bridge-specific)
├── PostProc/                       ← SCP destination for TDA capture data
│   └── <capture_dir>/              ← one folder per capture cycle
│       ├── master_0000_idx.bin
│       ├── master_0000_data.bin
│       ├── slave{1,2,3}_0000_data.bin
│       └── <capture_dir>.mmwave.json
└── python-result/                  ← processing outputs
    └── <capture_dir>/
        ├── ps_metrics.json              ← modal frequencies, displacement, max deflection
        ├── displacement_timeseries.csv  ← per-frame displacement time series
        ├── displacement.png
        ├── fft_spectrum.png
        └── ps_map.png
```

---

## Pipeline (pipeline.py)

Five sequential steps per cycle, runs continuously until `Ctrl+C`:

```
Step 1 — Capture      mimo.py --duration N --num-loops 1
Step 2 — Transfer     SCP root@192.168.33.180:/mnt/ssd/<dir> → ~/IoSAR-EdgeProcessing/PostProc/
Step 3 — Processing   mimo_processing.process_capture() → SLC.png, range-profile.png
Step 4 — PS Monitor   ps_monitoring.run_ps_monitoring() → ps_metrics.json, displacement_timeseries.csv
Step 5 — LoRa Uplink  lora_sender.send_lora() → 10-byte payload → Wio-E5 → TTN
```

**Common invocations:**
```bash
# Normal operation (60s capture, continuous)
python3 pipeline.py --duration 60

# Lab / vibrating table test (10s capture, 5s interval between cycles)
python3 pipeline.py --duration 10 --interval 5

# Reset PS map (new bridge deployment)
python3 pipeline.py --duration 60 --reset-ps

# Skip LoRa (no modem connected)
python3 pipeline.py --duration 10 --skip-lora

# Skip PS step (faster, SLC images only)
python3 pipeline.py --duration 10 --skip-ps

# Test LoRa with latest result without running pipeline
python3 lora_sender.py
python3 lora_sender.py --metrics /path/to/ps_metrics.json
```

**All pipeline.py arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `-t / --duration` | `10.0` | Capture duration in seconds |
| `--tda-ip` | `192.168.33.180` | TDA board IP |
| `-i / --interval` | `0.0` | Wait between cycles (seconds) |
| `--skip-transfer` | off | Skip SCP step |
| `--skip-processing` | off | Skip SLC/range-profile |
| `--skip-ps` | off | Skip PS monitoring |
| `--skip-lora` | off | Skip LoRa uplink |
| `--reset-ps` | off | Delete ps_map.json and relearn |
| `--lora-port` | `/dev/ttyUSB0` | Wio-E5 serial port |
| `--lora-appkey` | `562AD0AB...` | LoRaWAN APPKEY |

**Observed cycle times (10 s capture, Raspberry Pi 5):**
- No PS map (Pass 1 + Pass 2): ~1150 s (~19 min)
- With PS map cached (Pass 2 only): ~670 s (~11 min)
- 60 s capture with PS map: ~5800 s (~97 min)

---

## Signal Processing Chain (mimo_processing.py)

Per frame: `ADC data → Range FFT → Doppler FFT → Beamforming → SLC image [257 × 3992] complex64`

SLC image axes: `[257 angle bins, 3992 range bins]`

---

## PS Monitoring (ps_monitoring.py)

**Two-pass algorithm** (memory-efficient — never stores full SLC stack):

- **Pass 1 — ADI** (only on first run, result cached in `ps_map.json`):  
  Welford online algorithm → per-pixel mean amplitude + ADI (std/mean).  
  Select PS where `ADI < 0.3` AND `amplitude > 95th percentile`.  
  Cap at 50 PS candidates.

- **Pass 2 — Phase extraction**:  
  Re-process each frame, extract complex SLC only at PS coordinates → `[N_frames × 50]` array.

- **Displacement**: `d = (λ/4π) × unwrap(angle(ps_series))`, then `scipy.signal.detrend(type='linear')`.

- **FFT → Modal frequencies**:  
  Average power spectrum across all PS → `scipy.signal.find_peaks` → top-3 peaks in `[0.3, 10] Hz`.  
  Mode 1 = lowest freq, Mode 2 = next, Mode 3 = highest (ordered by frequency, not power).

**Key constants:**
```python
WARMUP_FRAMES  = 5      # skip first 5 frames (RF settling transient ~800 μm spike)
ADI_THRESHOLD  = 0.3
AMP_PERCENTILE = 95
MAX_PS_COUNT   = 50
FREQ_MIN, FREQ_MAX = 0.3, 10.0  # Hz
DT_DEFAULT     = 0.1            # 10 Hz frame rate
```

**PS map lifecycle:**
- Auto-created on first run from any capture of that bridge (takes ~2× longer for that cycle).
- Reused across all subsequent captures (stable reflectors assumed static).
- Delete `ps_map.json` or use `--reset-ps` when deploying on a different bridge.

**Note on bending vs torsional separation:**  
A single radar cannot distinguish bending from torsional modes. Mode 1/2/3 are ordered by frequency only. True bending/torsional separation requires a second radar on the opposite side of the bridge (future work).

---

## Output: ps_metrics.json

```json
{
  "capture": "mmwave_python_20260424_152235",
  "timestamp": "2026-04-24T15:40:07.000000",
  "freq_mode_1_hz": 1.485,
  "freq_mode_2_hz": 2.178,
  "freq_mode_3_hz": 2.673,
  "natural_frequency_hz": 1.485,
  "displacement_rms_mm": 0.001069,
  "displacement_rms_um": 1.069,
  "max_deflection_mm": 0.002893,
  "freq_resolution_hz": 0.099,
  "ps_count": 50,
  "ps_with_peak": 50,
  "num_frames_total": 106,
  "num_frames_used": 101,
  "warmup_frames": 5,
  "dt_s": 0.1,
  "total_duration_s": 10.1
}
```

**displacement_timeseries.csv columns:**
```
time_s, datetime, disp_mean_mm, disp_max_abs_mm
```

**System noise floor (static ceiling, no vibration):**
- `freq_mode_1_hz ≈ 0.365 Hz` (noise artifact, not real structure)
- `displacement_rms_um ≈ 2.684 μm`
- Real structural signal must be significantly above this floor (target ≥ 20 μm for vibrating table test).

---

## LoRa Uplink (lora_sender.py)

**Hardware:** Wio-E5 DevKit (SeeedStudio) — CP2102N USB-UART — `/dev/ttyUSB0` — 9600 baud  
**Network:** LoRaWAN OTAA, APPKEY `562AD0AB720BA25D830E20164D3CC1B3`

**Payload format — 10 bytes, big-endian:**

| Byte | Field | Encoding | Resolution | Max |
|------|-------|----------|------------|-----|
| 0–3 | Unix timestamp | uint32 | 1 s | 2106 |
| 4–5 | `freq_mode_1_hz` | uint16 × 100 | 0.01 Hz | 655.35 Hz |
| 6–7 | `displacement_rms_mm` | uint16 × 1000 | 0.001 mm (1 μm) | 65.5 mm |
| 8–9 | `max_deflection_mm` | uint16 × 1000 | 0.001 mm (1 μm) | 65.5 mm |

**Total: 10 bytes** (well within LoRaWAN SF10 limit of 51 bytes)

**AT command sequence:**
```
AT                                    → +AT: OK
AT+KEY=APPKEY,"<key>"                 → +KEY: APPKEY ...
AT+JOIN                               → +JOIN: Network joined  (OTAA, ~6s)
AT+MSGHEX="<10-byte-hex>"            → +MSGHEX: Done
```

**Backward compatibility:** `lora_sender.py` reads `freq_mode_1_hz` or falls back to `natural_frequency_hz`; reads `displacement_rms_mm` or converts from `displacement_rms_um`.

**TTN Payload Formatter (uplink decoder — JavaScript):**
```javascript
function decodeUplink(input) {
  var bytes = input.bytes;
  var data  = {};

  var ts = ((bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3]) >>> 0;
  data.timestamp_unix        = ts;
  data.timestamp_iso         = new Date(ts * 1000).toISOString();
  data.natural_frequency_hz  = ((bytes[4] << 8) | bytes[5]) / 100.0;
  data.displacement_rms_mm   = ((bytes[6] << 8) | bytes[7]) / 1000.0;
  data.displacement_rms_um   = (bytes[6] << 8) | bytes[7];
  data.max_deflection_mm     = ((bytes[8] << 8) | bytes[9]) / 1000.0;
  data.max_deflection_um     = (bytes[8] << 8) | bytes[9];
  data.latitude              = 43.8156;   // Muroran IT (hardcoded)
  data.longitude             = 140.9723;

  return { data: data };
}
```

**Verified received payload (2026-04-24, TTN app `iosar-imrsl`, device `gb-sar-01`):**
```
hex:   69 EB 8E D7  00 94  00 01  00 03
→ ts:  2026-04-24T15:40:07 JST
→ freq: 1.48 Hz  |  rms: 1 μm  |  max: 3 μm
RSSI: -9 dBm, SNR: 10.5 dB  (gateway: gw-imrsl)
```

---

## Known Issues & Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Only 6–10 frames per 10 s capture | No `time.sleep()` between start/stop frame | Added `time.sleep(args.duration)` in mimo.py |
| OOM killed for 60 s capture | Full SLC stack 607×[257,3992]×8B ≈ 5 GB | Two-pass Welford algorithm (O(H×W) memory) |
| Initial ~800 μm transient spike | RF settling in first 1–2 frames | `WARMUP_FRAMES = 5` + detrend + Hanning window |
| Pipeline fell back to wrong capture dir after Ctrl+C | `run_capture()` returned stale JSON on interrupt | Return `None` when no new JSON detected |
| RF init failure status -8 | Intermittent hardware-level TDA init error | Pipeline auto-retries after 10 s |
| LoRa payload all zeros | ps_metrics.json missing new fields (old ps_monitoring.py) | Sync updated ps_monitoring.py to Pi |
| `+JOIN: Done` matched as MSGHEX "Done" | Join response leaked into MSGHEX buffer | `time.sleep(2) + reset_input_buffer()` after join |

---

## SSH/SCP to TDA Board

```bash
# Test connectivity
ssh -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no root@192.168.33.180

# List captures on SSD
ssh -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no root@192.168.33.180 "ls /mnt/ssd/"

# Manual SCP
scp -O -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no -r \
    root@192.168.33.180:/mnt/ssd/<capture_dir> ~/IoSAR-EdgeProcessing/PostProc/
```

## SSH to Raspberry Pi

```bash
ssh imrsl@imrslpi5-02   # password: imrsl2022
```

---

## Planned Next Steps

- [ ] **Vibrating table validation** — set 2–5 Hz, amplitude ≥ 20 μm, verify `freq_mode_1_hz` matches table setting
- [ ] **Bridge deployment** — reset PS map with `--reset-ps`, run `--duration 60` for 0.017 Hz freq resolution
- [ ] **Dashboard** — connect TTN webhook to Grafana/custom dashboard; plot `natural_frequency_hz` trend and `displacement_timeseries.csv`
- [ ] **Bending/torsional separation** — add second radar on opposite bridge side; compare symmetric vs antisymmetric PS phase response
