# Experiment Plan: Indoor Static Capture — framePeriodicity 50 ms Verification
**Experiment Date:** 2026-05-12  
**Location:** Indoor Lab — IMRSL, Muroran Institute of Technology  
**Author:** Rogers Dwiputra Setiady  
**Branch:** `Experiment-Indoor-20260512`

---

## 1. Objective

Confirm that `framePeriodicity = 50 ms` (20 Hz frame rate) is correctly applied
end-to-end in the RPI capture pipeline after the repository was synchronized.

This experiment follows the outdoor validation (2026-05-10) where the Pi was found
to be running a pre-sync version with `framePeriodicity = 100 ms`. The indoor test
provides a clean controlled baseline:
- No vibration (static corner reflector)
- Known target range (~4 m)
- Short capture (10 s)
- Both GT and RPI captures under identical RF configuration

---

## 2. Hypothesis

After syncing the Raspberry Pi to the current `main` branch (commit ≥ `e183e85`),
the RPI pipeline will produce captures with `framePeriodicity_msec = 50.0` in the
`.mmwave.json` config file, matching the GT Lua configuration (`Inter_Frame_Interval = 50`).
Both captures should show the corner reflector at ~4 m range with equivalent SNR.

---

## 3. Experimental Setup

### 3.1 Scene
| Item | Value |
|------|-------|
| Target | Trihedral corner reflector (standard radar calibration target) |
| Target range | ~4 m (measured from radar aperture) |
| Target motion | Static (no vibration source) |
| Environment | Indoor lab, no wind, controlled temperature |

### 3.2 Radar Hardware
| Parameter | Value |
|-----------|-------|
| System | TIDEP-01012 — 4× AWR2243, 12 TX × 16 RX virtual |
| TDA board | TDA2XX, IP `192.168.33.180` |
| Processing host | Raspberry Pi 5 (`imrslpi5-02`) — must be synced to latest `main` |

---

## 4. RF Configuration

All parameters identical to the outdoor experiment (2026-05-10 GT), **except** frame count:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Start frequency | 77 GHz | Standard |
| Frequency slope | 79.0327 MHz/μs | Standard |
| ADC samples | 256 | Standard |
| ADC sampling freq | 8000 ksps | Standard |
| Ramp end time | 40 μs | Standard |
| Idle time | 5 μs | Standard |
| Chirp loops / frame | 16 | Standard |
| **Frame periodicity** | **50 ms (20 Hz)** | Key parameter under validation |
| Frame count (GT) | **200** (finite) | 200 × 50 ms = 10 s |
| Frame count (RPI) | continuous for 10 s | `--duration 10` |

**Derived radar parameters:**
- Max range: `c × ADC_samples / (2 × slope × adc_sampling_freq)` ≈ 15.2 m (4 m target well within range)
- Range resolution: `c / (2 × slope × ramp_end_time)` ≈ 5.9 cm
- Frequency resolution (at 20 Hz, 200 frames): `1 / (200 × 0.05)` = 0.1 Hz

---

## 5. Files

### 5.1 Ground Truth (mmWave Studio GUI, Windows)
| File | Purpose |
|------|---------|
| `20260512_GroundTruth.lua` | RF configuration (run first in mmWave Studio) |
| `20260512_Cascade_Capture_Indoor.lua` | Framing and capture control (`framing_type = 1`, finite) |

**Capture directory naming:** `GT_static_4m_10s_YYMMDD_HHMMSS` (auto-appended by script)

### 5.2 RPI Pipeline
```bash
# Ensure Pi is synced first
git pull origin main

# Run capture (skip PS and LoRa — not needed for this validation)
python3 pipeline.py --duration 10 --skip-ps --skip-lora
```
**Capture directory naming:** `RPI_indoor_static_4m_10s_YYYYMMDD_HHMMSS`

---

## 6. Procedure

1. **Sync Raspberry Pi** — `git pull origin main` on `imrslpi5-02`, verify `framePeriodicity = 50` in `mimo.py`
2. **Set up corner reflector** — place at ~4 m directly in front of radar, facing broadside
3. **GT capture** — run `20260512_GroundTruth.lua` then `20260512_Cascade_Capture_Indoor.lua` in mmWave Studio
4. **RPI capture** — run `python3 pipeline.py --duration 10 --skip-ps --skip-lora` on Pi
5. **Transfer GT data** — SCP from TDA to `~/IoSAR-EdgeProcessing/PostProc/` on Pi (or direct to analysis machine)
6. **Process both** — run `mimo_processing.process_capture()` on both directories to generate SLC.png and range-profile.png
7. **Compare** — verify `framePeriodicity_msec = 50.0` in both `.mmwave.json` files, compare SLC images and range profiles

---

## 7. Success Criteria

| Criterion | Expected |
|-----------|----------|
| RPI `.mmwave.json`: `framePeriodicity_msec` | `50.0` |
| GT `.mmwave.json` / `test_param.m`: `framePeriodicity` | `5.000000e-02` (50 ms) |
| RPI frame count in 10 s at 20 Hz | ~200 frames (± settling frames) |
| Corner reflector visible in SLC | Peak at angle ≈ 0°, range ≈ 4 m |
| GT vs RPI SLC: target position | Identical |
| GT vs RPI range profile: peak | Same range (±1 range bin ≈ 5.9 cm), same amplitude |

---

## 8. Relationship to Prior Work

| Experiment | Date | Key Finding |
|-----------|------|-------------|
| Outdoor (vibrating target, ~10 m) | 2026-05-10 | RPI and GT SLC/range profiles are visually identical — pipeline validated. Pi had 100 ms (unsync'd). |
| **Indoor (corner reflector, ~4 m)** | **2026-05-12** | **Verify 50 ms frame rate works end-to-end after Pi sync.** |
| Vibrating table validation | TBD | Verify modal frequency detection at 2–5 Hz, amplitude ≥ 20 μm |
| Bridge deployment | TBD | Full pipeline with LoRa uplink, 60 s captures |

See `experiment-log/20260510 Outdoor/Validation-RPI-vs-GT-20260510.md` for the full outdoor validation report.
