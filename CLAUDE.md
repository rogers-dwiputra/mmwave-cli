# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated pipeline for **Bridge Structural Health Monitoring** using a TIDEP-01012 MIMO Cascade Radar (77 GHz, 4-chip AWR2243 cascade). The system continuously captures radar data, transfers it to a processing host, runs edge processing, extracts structural vibration metrics via Permanent Scatterer (PS) interferometry, and transmits results to the cloud via LoRaWAN.

**Research context:** PhD project at IMRSL, Muroran Institute of Technology.  
**Goal:** Detect bridge dominant vibration frequency and displacement via sub-mm radar interferometry, transmit via LoRaWAN (Wio-E5 → TTN) for remote dashboard monitoring.

**Status:** Full pipeline implemented end-to-end. Next milestone: bridge deployment demo on 2026-05-25.

---

## Build & Setup

### Python dependencies (Raspberry Pi)
```bash
pip install cython pyserial numpy scipy matplotlib
```

### Build the `mmwcas` Cython extension
```bash
make build                         # full clean + rebuild
python setup.py build_ext --inplace  # Cython only (faster)
```
After a successful build, `mmwcas.cpython-*.so` appears in the repo root.

### Verify the build
```bash
python3 -c "import mmwcas; print('mmwcas OK')"
```

---

## Hardware

| Component | Details |
|-----------|---------|
| Radar | TIDEP-01012 — 4× AWR2243, 12 TX × 16 RX virtual, 77 GHz |
| DSP board | TDA2XX (mmWave DSP EVM) |
| TDA IP | `192.168.33.180` (static, over Ethernet) |
| TDA data storage | `/mnt/ssd/<capture_dir>/` (auto-deleted after SCP transfer) |
| Processing host | Raspberry Pi 5 (ARM Cortex-A76), hostname `imrslpi5-02`, user `imrsl`, password `imrsl2022` |
| LoRaWAN modem | Wio-E5 Development Kit (SeeedStudio) — `/dev/ttyUSB0`, 9600 baud, CP2102N |
| LoRaWAN network | The Things Stack (TTN) — tenant `imrsl`, app `iosar-imrsl`, device `gb-sar-01` |

**Key radar parameters (`mimo.py` `config_dict`):**
- `framePeriodicity = 50 ms` → frame rate = 20 Hz
- `numAdcSamples = 512`, `adcSamplingFrequency = 8000 ksps`
- `frequencySlope = 20 MHz/μs`, `idleTime = 5 μs`, `adcStartTime = 6 μs`, `rampEndTime = 75 μs`
- `numLoops = 16` chirp loops per frame
- **Bandwidth = 1.28 GHz**, **max range = 60 m**, **range resolution ≈ 11.7 cm** (10.4 cm with Hanning window)
- `dt` in edge processing is read automatically from `.mmwave.json` per capture (falls back to `DT_DEFAULT = 0.05`)

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
├── mmwave_json_files/              ← generated .mmwave.json config files (per capture, moved into capture dir after SCP)
├── dashboard/
│   ├── ttn-uplink-formatter.js     ← TTN payload decoder (paste into TTN Console)
│   ├── grafana-dashboard-v0.1.json ← importable Grafana dashboard
│   └── telegraf/                   ← Telegraf config deployed on VPS
│       ├── telegraf.conf
│       ├── docker-compose.yml      ← running on root@148.230.102.157
│       └── .env.example
└── ti/                             ← TI SDK headers and firmware (do not modify)

~/IoSAR-EdgeProcessing/             ← edge processing (separate git repo, separate from mmwave-cli)
├── mimo_processing.py              ← range FFT → Doppler FFT → beamforming → SLC image
├── ps_monitoring.py                ← PS selection → phase extraction → FFT → dominant frequency
├── ps_map.json                     ← learned PS candidate map (auto-generated, bridge-specific)
├── PostProc/                       ← SCP destination for TDA capture data
└── python-result/                  ← processing outputs (ps_metrics.json, PNGs, CSV)
```

`pipeline.py` dynamically imports `mimo_processing.py` and `ps_monitoring.py` from `~/IoSAR-EdgeProcessing/` at runtime using `importlib`. Changes to those files take effect immediately without rebuilding.

---

## Pipeline (pipeline.py)

Five sequential steps per cycle, runs continuously until `Ctrl+C`:

```
Step 1 — Capture      mimo.py --duration N --num-loops 1 --directory <label>
Step 2 — Transfer     SCP root@TDA:/mnt/ssd/<dir> → ~/IoSAR-EdgeProcessing/PostProc/
                      then: rm -rf /mnt/ssd/<dir> on TDA (auto-delete after transfer)
Step 3 — Processing   [DEBUG only] mimo_processing.process_capture() → SLC.png, range-profile.png
Step 4 — PS Monitor   ps_monitoring.run_ps_monitoring() → ps_metrics.json, displacement_timeseries.csv
Step 5 — LoRa Uplink  lora_sender.send_lora() → 10-byte payload → Wio-E5 → TTN
```

**Step 3 (SLC + range-profile) is SKIPPED by default** — only generated when `--debug` flag is passed.  
This saves ~120 s per cycle during long monitoring sessions.

**Common invocations:**
```bash
# Normal bridge monitoring (demo 2026-05-25)
python3 pipeline.py --duration 15 --label RPI_python_bridge

# With manually selected PS coordinates (skip ADI computation every cycle)
python3 pipeline.py --duration 15 --label RPI_python_bridge --ps-file ~/ps_manual.json

# Debug mode: also generates SLC and range-profile images
python3 pipeline.py --duration 10 --label RPI_python_test --debug

# Lab / vibrating table test, no LoRa modem
python3 pipeline.py --duration 10 --label RPI_python_sine_2hz --skip-lora

# Reset PS map (new bridge / new deployment site)
python3 pipeline.py --duration 15 --label RPI_python_bridge --reset-ps

# Process only (skip capture + transfer)
python3 pipeline.py --skip-transfer --skip-ps --debug  # SLC only on already-transferred data

# Test LoRa send with latest result
python3 lora_sender.py
```

**Run with nohup (long monitoring sessions):**
```bash
nohup python3 pipeline.py --duration 15 --label RPI_python_bridge --ps-file ~/ps_manual.json \
  > ~/pipeline_$(date +%y%m%d_%H%M%S).log 2>&1 &
tail -f ~/pipeline_*.log
```

**Key pipeline arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `-t` / `--duration` | `10.0` | Capture duration in seconds |
| `--label` | `RPI_python` | Prefix for capture directory name (timestamp appended) |
| `--tda-ip` | `192.168.33.180` | TDA board IP |
| `-i` / `--interval` | `0.0` | Wait between cycles (s) |
| `--debug` | off | Enable SLC + range-profile image generation (Step 3) |
| `--ps-file` | None | Manual PS JSON from select_ps_manual.m (skips ADI) |
| `--reset-ps` | off | Delete ps_map.json to force ADI recomputation |
| `--skip-transfer` | off | Skip SCP transfer |
| `--skip-ps` | off | Skip PS monitoring |
| `--skip-lora` | off | Skip LoRa uplink |
| `--lora-port` | `/dev/ttyUSB0` | Wio-E5 serial port |

**Estimated cycle times (15 s capture, Raspberry Pi 5, with ps_map.json cached):**
- Step 1 Capture: ~20 s (15 s capture + arm/disarm overhead)
- Step 2 Transfer: ~50 s (SCP ~320 MB, 4 devices × 80 MB)
- Step 3 Processing: ~30 s (only when --debug)
- Step 4 PS Monitoring: ~120–180 s (Pass 2 only with ps_map.json)
- Step 5 LoRa: ~5–10 s
- **Total per cycle: ~4–5 minutes**

---

## Signal Processing Chain (mimo_processing.py)

Per frame: `ADC data → Range FFT → Doppler FFT → Beamforming → SLC image [257 × 3992] complex64`

SLC image axes: `[257 angle bins, 3992 range bins]`

**Derived radar parameters (Mizumoto Bridge 2026-05-25 config):**
- ADC samples: 512, sample rate: 8 MHz → ramp time = 64 μs
- Bandwidth = 1.28 GHz → range resolution = **11.7 cm** (10.4 cm with Hanning window)
- Max range = 60 m
- Range FFT: 4096-point (zero-padded from 512) → range bin = 1.465 cm
- Center frequency: 77.76 GHz → λ = 3.858 mm (ps_monitoring uses 77.4742 GHz MATLAB ref)
- `RATIO_FFT = 512/4096 = 0.125`

---

## PS Monitoring (ps_monitoring.py)

**Three PS source priority (select_ps()):**
1. `--ps-file` — manually selected JSON from MATLAB `select_ps_manual.m` (**recommended for deployment**)
2. `ps_map.json` — previously auto-computed and cached
3. ADI computation (Welford online algorithm) — fallback, runs only on first cycle

**Two-pass algorithm** (memory-efficient — never stores full SLC stack):
- **Pass 1 — ADI** (only when no ps_map.json and no --ps-file):  
  Welford online → per-pixel mean amplitude + ADI (std/mean).  
  Select PS where `ADI < 0.3` AND `amplitude > 95th percentile`. Cap at 50 PS.
- **Pass 2 — Phase extraction**:  
  Re-process each frame, extract complex SLC only at PS coordinates.

**Displacement:** `d = (λ/4π) × unwrap(angle(ps_series))`, then `scipy.signal.detrend(type='linear')`

**Dominant frequency:** Average power spectrum across all PS → `scipy.signal.find_peaks` → pick the **single highest-power peak** in `[0.3, 10] Hz`. This is the dominant frequency (consistent with MATLAB supervisor approach).

**Key constants:**
```python
WARMUP_FRAMES  = 5        # skip first 5 frames (RF settling transient)
ADI_THRESHOLD  = 0.3
AMP_PERCENTILE = 95
MAX_PS_COUNT   = 50
FREQ_MIN, FREQ_MAX = 0.3, 10.0   # Hz
DT_DEFAULT     = 0.05             # 20 Hz fallback; actual dt read from .mmwave.json per capture
```

**Frame timing auto-detection:** `_read_dt_from_json()` reads `framePeriodicity_msec` from the capture's `.mmwave.json`. Falls back to `DT_DEFAULT = 0.05` (50 ms / 20 Hz) if not found. This is critical — wrong dt doubles/halves all detected frequencies.

---

## Output: ps_metrics.json

```json
{
  "capture": "RPI_python_bridge_260525_080012",
  "timestamp": "2026-05-25T08:05:30.000000",
  "dominant_frequency_hz": 2.034,
  "displacement_rms_mm": 0.000842,
  "displacement_rms_um": 0.842,
  "max_deflection_mm": 0.002156,
  "freq_resolution_hz": 0.067,
  "ps_count": 12,
  "ps_with_peak": 10,
  "num_frames_used": 245,
  "num_frames_total": 250,
  "warmup_frames": 5,
  "dt_s": 0.05,
  "total_duration_s": 12.25
}
```

**System noise floor (static target, no vibration):**
- `dominant_frequency_hz ≈ 0.365 Hz` (noise artifact, not real structure)
- `displacement_rms_um ≈ 2.7 μm`

---

## LoRa Uplink (lora_sender.py)

**Payload format — 10 bytes, big-endian:**

| Byte | Field | Encoding | Resolution |
|------|-------|----------|------------|
| 0–3 | Unix timestamp | uint32 | 1 s |
| 4–5 | `dominant_frequency_hz` | uint16 × 100 | 0.01 Hz |
| 6–7 | `displacement_rms_mm` | uint16 × 1000 | 0.001 mm (1 μm) |
| 8–9 | `max_deflection_mm` | uint16 × 1000 | 0.001 mm (1 μm) |

**AT command sequence:** `AT` → `AT+KEY=APPKEY,"<key>"` → `AT+JOIN` → `AT+MSGHEX="<hex>"`

**Backward compatibility:** `lora_sender.py` reads `dominant_frequency_hz`, falls back to `freq_mode_1_hz`, then `natural_frequency_hz`.

---

## Cloud Monitoring Stack

```
Raspberry Pi → LoRa → TTN → MQTT → Telegraf → InfluxDB Cloud → Grafana
```

| Component | Details |
|-----------|---------|
| TTN app | `iosar-imrsl`, tenant `imrsl`, device `gb-sar-01` |
| TTN MQTT host | `imrsl.as1.cloud.thethings.industries:8883` (TLS) |
| TTN MQTT username | `iosar-imrsl@imrsl` |
| TTN MQTT topic | `v3/iosar-imrsl@imrsl/devices/+/up` |
| Telegraf | Docker on VPS `148.230.102.157`, at `/opt/telegraf-iosar/` |
| InfluxDB Cloud | `us-east-1-1.aws.cloud2.influxdata.com`, org `fa0efd0230808dbd`, bucket `iosar` |
| InfluxDB measurement | `uplink`, tag `device_id=gb-sar-01` |
| Grafana | `https://imrsl.grafana.net/` |

**Key InfluxDB fields** (written by TTN formatter → Telegraf):
- `dominant_frequency_hz` — highest-power vibration peak in 0.3–10 Hz band
- `displacement_rms_mm` — RMS displacement across all PS candidates
- `max_deflection_mm` — peak displacement over capture window

**TTN Payload Formatter** at `dashboard/ttn-uplink-formatter.js` — paste into TTN Console > Applications > iosar-imrsl > Payload formatters > Uplink.

**Telegraf management on VPS:**
```bash
ssh root@148.230.102.157
cd /opt/telegraf-iosar
docker compose logs -f          # monitor live
docker compose restart          # restart after config change
```

**InfluxDB Flux query template:**
```flux
from(bucket: "iosar")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "uplink")
  |> filter(fn: (r) => r["device_id"] == "gb-sar-01")
  |> filter(fn: (r) => r["_field"] == "dominant_frequency_hz")
```

---

## Known Issues & Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Only 6–10 frames per 10 s capture | No `time.sleep()` between start/stop | Added `time.sleep(args.duration)` in mimo.py |
| OOM killed for 60 s capture | Full SLC stack ≈ 5 GB RAM | Two-pass Welford algorithm (O(H×W) memory) |
| Initial ~800 μm transient spike | RF settling in first 1–2 frames | `WARMUP_FRAMES = 5` + detrend + Hanning window |
| All frequencies doubled for RPI captures | DT_DEFAULT=0.05 used for 100ms captures | `_read_dt_from_json()` auto-reads framePeriodicity per capture |
| LoRa payload frequency field = 0 | Old ps_metrics.json with `freq_mode_1_hz` field | `lora_sender.py` has backward-compat fallback chain |
| `+JOIN: Done` matched MSGHEX "Done" | Join response leaked into MSGHEX buffer | `time.sleep(2) + reset_input_buffer()` after join |
| TDA SSD fills up during long sessions | Raw data not deleted after transfer | Auto `rm -rf /mnt/ssd/<dir>` via SSH after SCP succeeds |
| process_vibration_experiment.py crash | `summary[0]` when 0 captures found | `if not summary: return` guard added |

---

## SSH/SCP Access

```bash
# SSH to Raspberry Pi
ssh imrsl@imrslpi5-02           # password: imrsl2022

# SSH to TDA board (from Raspberry Pi)
ssh -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no root@192.168.33.180

# Manual SCP from TDA
scp -O -oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -oStrictHostKeyChecking=no -r \
    root@192.168.33.180:/mnt/ssd/<capture_dir> ~/IoSAR-EdgeProcessing/PostProc/
```

---

## Capture Directory Naming

Format: `<label>_<YYMMDD>_<HHMMSS>`  
Example: `RPI_python_bridge_260525_080012`

The `--label` argument sets the prefix. Timestamp is appended automatically by `mimo.py`.

---

## Planned Next Steps

- [ ] **Bridge demo 2026-05-25** — full pipeline 8am–3pm, corner reflector at midspan
- [ ] **PS selection at site** — run `select_ps_manual.m` on first capture, use `--ps-file` for all subsequent
- [ ] **Corner reflector** — trihedral CR at midspan, ~30–45° elevation angle from riverbank
- [ ] **Dashboard v0.2** — per-PS displacement timeseries graph in Grafana
