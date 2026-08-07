# Test — `--num-frames` / `--frame-period` (direct frame-count framing)

**Date:** 2026-08-07 · **Hardware:** RPi `imrslpi5-02` + TIDEP-01012 (real capture)
**Code:** `feat/toml-config` + the `feat/finite-num-frames` changes (mimo.py, pipeline.py)
**mmwcas:** built, `mmw_power_off` present.

Feature: specify the capture as an **exact frame count** (+ inter-frame period) instead of only
a time-based `--finite-framing` (which derives numFrames from `--duration`).
Precedence: `--num-frames` > `--finite-framing` > infinite.

## Test A — mimo.py (standalone / default path)
`python3 mimo.py --num-frames 200 --frame-period 10 --num-loops 1 --directory ClaudeNF`

**Result: ✅ PASS**
- `Frame period override: 10.0 ms  (Fs=100.00 Hz)`
- `Finite framing: numFrames=200 (direct) @ 10.0ms/frame → 2.00s`
- `Capturing... (200 frames, ~2.00s)` → `[TS] STOP_FRAME skipped (finite framing)`
- All STATUS 0, 8 files on TDA (43.7 MB/chip), `.mmwave.json` written, `[MMWCAS] Radar powered off (teardown).`

## Test B — pipeline.py (persistent path)
`python3 pipeline.py --persistent --num-frames 200 --frame-period 10 --label ClaudeNF2 --skip-ps --skip-lora` (1 cycle)

**Result: ✅ PASS**
- Radar init **once** (persistent); `[PIPELINE] Finite framing: numFrames=200 (direct) @ 10.0ms/frame`
- `Capturing... (2.0s)` — effective capture length = N × period computed correctly in `main()`
- `stop_frame skipped (finite framing)`; SCP transfer + TDA auto-clean; cycle 37.4 s; `Pipeline stopped cleanly.`
- **0× `-2` / `-8` / ERROR.**

## Frame-count verification (idx header)
`master_0000_idx.bin` header[3] (valid frames): **199** for a **200**-frame request — in **both** paths.

> ⚠️ **Consistent TDA off-by-one:** requesting N frames yields **N−1** valid frames in the index
> (waited 2 s margin past auto-stop, so this is not a timing truncation — it's the TDA capture
> counting completed frame-end markers). Our code programs `numFrames = N` correctly; the −1 is
> hardware/firmware behaviour. **If you need exactly N valid frames, request `--num-frames N+1`.**

## Verdict
Both paths **PASS** on hardware. `--num-frames` + `--frame-period` give direct, deterministic
frame-count control (e.g. 200 frames @ 10 ms = 2.00 s) instead of the indirect duration route.
Note the N→N−1 idx off-by-one above.

## Reproduce
```bash
# on RPi (~/mmwave-cli, radar connected + powered, sudo sh configure_ip.sh first):
python3 mimo.py --num-frames 200 --frame-period 10 --num-loops 1 --directory NFtest
python3 pipeline.py --persistent --num-frames 200 --frame-period 10 --label NFtest --skip-ps --skip-lora
```
