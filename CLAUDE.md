# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated pipeline for **Bridge Structural Health Monitoring** using a TIDEP-01012 MIMO Cascade Radar (77 GHz, 4-chip AWR2243 cascade). The system continuously captures radar data, transfers it to a processing host, runs edge processing, extracts structural vibration metrics via Permanent Scatterer (PS) interferometry, and transmits results to the cloud via LoRaWAN.

**Research context:** PhD project at IMRSL, Muroran Institute of Technology.  
**Goal:** Detect bridge modal frequencies and displacement via sub-mm radar interferometry, transmit via LoRaWAN (Wio-E5 → TTN) for remote dashboard monitoring.

**Status:** Full pipeline operational end-to-end (capture → edge processing → LoRa → TTN). Validated in lab (static ceiling test). Next: vibrating table validation, then bridge deployment.

---

## Build & Setup

### Python dependencies (Raspberry Pi)
```bash
pip install cython pyserial numpy scipy
```

### Build the `mmwcas` Cython extension (Python path — preferred)
```bash
# Full clean + C objects + Cython extension
make build

# Cython extension only (faster rebuild after Python/Cython changes)
make build-cython
# or equivalently:
python setup.py build_ext --inplace
```
After a successful build, `mmwcas.cpython-*.so` appears in the repo root.

### Build the standalone C binary (`mmwave`)
```bash
# Compile and install to /usr/local/bin
sudo make install

# Compile only (no install)
make all

# Clean build artifacts
make clean
```

### Verify the build
```bash
python3 -c "import mmwcas; print('mmwcas OK')"
mmwave -h   # if installed via sudo make install
```

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

**Key radar parameters (`mimo.py` `config_dict`):**
- `framePeriodicity = 50 ms` → frame rate = 20 Hz (note: was 100 ms / 10 Hz in earlier experiments)
- `numAdcSamples = 256`, `adcSamplingFrequency = 8000 ksps`
- `frequencySlope = 79.0327 MHz/μs`, `rampEndTime = 40 μs`
- `numLoops = 16` chirp loops per frame
- λ ≈ 3.896 mm at 77 GHz
- `dt` in edge processing must match the actual `framePeriodicity` configured here

---

## Repository Structure

```
mmwave-cli/                         ← this repo (runs on Raspberry Pi ~/mmwave-cli/)
├── mimo.py                         ← radar control: configure, arm, capture, stop
├── mimo.c / mimo.h                 ← standalone C binary (legacy/alternate path)
├── mmwcas.pyx / mmwcas.pyi         ← Cython wrapper — compiled to mmwcas.so (Python import)
├── setup.py                        ← build mmwcas Cython extension
├── makefile                        ← build C binary + Cython extension
├── pipeline.py                     ← automated 5-step pipeline (main entry point)
├── lora_sender.py                  ← LoRaWAN uplink via Wio-E5 AT commands (Step 5)
├── utility.py                      ← check_captured_files(), export_config_to_json(), signal_handler()
├── config_export.py                ← standalone duplicate of export_config_to_json() (not used by pipeline)
├── multiradar.py                   ← experimental dual-radar script (not part of pipeline)
├── mmwave_json_files/              ← generated .mmwave.json config files (per capture)
├── config/                         ← TOML radar config files (for standalone C binary)
└── ti/                             ← TI SDK headers and firmware (do not modify)

~/IoSAR-EdgeProcessing/             ← edge processing (separate repo, OneDrive-synced)
├── mimo_processing.py              ← range FFT → Doppler FFT → beamforming → SLC image
├── ps_monitoring.py                ← PS selection → phase extraction → FFT → modal frequencies
├── ps_map.json                     ← learned PS candidate map (auto-generated, bridge-specific)
├── PostProc/                       ← SCP destination for TDA capture data
└── python-result/                  ← processing outputs (ps_metrics.json, displacement_timeseries.csv, PNGs)
```

`pipeline.py` dynamically imports `mimo_processing.py` and `ps_monitoring.py` from `~/IoSAR-EdgeProcessing/` at runtime using `importlib`. Changes to those files take effect immediately without rebuilding.

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
python3 pipeline.py --duration 60                        # Normal operation
python3 pipeline.py --duration 10 --interval 5          # Lab / vibrating table test
python3 pipeline.py --duration 60 --reset-ps            # New bridge deployment
python3 pipeline.py --duration 10 --skip-lora           # No modem connected
python3 pipeline.py --duration 10 --skip-ps             # SLC images only (faster)
python3 lora_sender.py                                   # Test LoRa with latest result
```

**Observed cycle times (10 s capture, Raspberry Pi 5):**
- No PS map (Pass 1 + Pass 2): ~1150 s (~19 min)
- With PS map cached (Pass 2 only): ~670 s (~11 min)
- 60 s capture with PS map: ~5800 s (~97 min)

**Capture directory** is hardcoded in `pipeline.py:run_capture()` via `--directory RPI_python_sine_2hz_1mm_10s_continuous`. Change this string for new experiment series.

---

## Signal Processing Chain (mimo_processing.py)

Per frame: `ADC data → Range FFT → Doppler FFT → Beamforming → SLC image [257 × 3992] complex64`

SLC image axes: `[257 angle bins, 3992 range bins]`

---

## PS Monitoring (ps_monitoring.py)

**Two-pass algorithm** (memory-efficient — never stores full SLC stack):

- **Pass 1 — ADI** (only on first run, result cached in `ps_map.json`):  
  Welford online algorithm → per-pixel mean amplitude + ADI (std/mean).  
  Select PS where `ADI < 0.3` AND `amplitude > 95th percentile`. Cap at 50 PS candidates.

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
DT_DEFAULT     = 0.1            # must match framePeriodicity in mimo.py
```

**PS map lifecycle:**
- Auto-created on first run (takes ~2× longer for that cycle).
- Reused across all subsequent captures (stable reflectors assumed static).
- Delete `ps_map.json` or use `--reset-ps` when deploying on a different bridge.

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
  "num_frames_used": 101,
  "dt_s": 0.1
}
```

**System noise floor (static ceiling, no vibration):**
- `freq_mode_1_hz ≈ 0.365 Hz` (noise artifact, not real structure)
- `displacement_rms_um ≈ 2.684 μm`
- Real structural signal must be significantly above this floor (target ≥ 20 μm for vibrating table test).

---

## LoRa Uplink (lora_sender.py)

**Payload format — 10 bytes, big-endian:**

| Byte | Field | Encoding | Resolution |
|------|-------|----------|------------|
| 0–3 | Unix timestamp | uint32 | 1 s |
| 4–5 | `freq_mode_1_hz` | uint16 × 100 | 0.01 Hz |
| 6–7 | `displacement_rms_mm` | uint16 × 1000 | 0.001 mm (1 μm) |
| 8–9 | `max_deflection_mm` | uint16 × 1000 | 0.001 mm (1 μm) |

**AT command sequence:** `AT` → `AT+KEY=APPKEY,"<key>"` → `AT+JOIN` → `AT+MSGHEX="<hex>"`

**Backward compatibility:** `lora_sender.py` reads `freq_mode_1_hz` or falls back to `natural_frequency_hz`; reads `displacement_rms_mm` or converts from `displacement_rms_um`.

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
