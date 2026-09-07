# MizumotoBridge Continuous Monitoring — Deployment Summary (2026-09-07)

Summary of the phase-eval feature build + production swap done in this session, before a ~12-day unattended run on `imrslpi5-02`.

## ⚠️ PENDING FIX — do this first when reconnected (2026-09-08, not yet deployed)

A post-swap amplitude comparison (102 real `_SLC.mat` files, 2026-09-04..07) found the live `ps_manual_span5.json` target coordinates are worse than the original analysis: dimmer at 4/5 points, and 3 of 5 (PierLeft/MidLeft/MidSpan) had drifted ~3.4–3.7 m from the original `pier_kiri`/`quarter_kiri`/`midspan`/`quarter_kanan`/`pier_kanan` points — not a refinement. The fix is committed (`422eca9`, `feat/finite-num-frames`) but **not deployed** — no RPi access since 2026-09-07 ~22:00 JST.

**Steps, in this order:**
1. `cd ~/mmwave-cli && git pull`
2. `cp ps_manual_span5.json ~/ps_manual_span5.json` (overwrites the RPi-local copy the pipeline actually reads)
3. **Archive, don't just leave, the long-term history before restarting:**
   `mv ~/IoSAR-EdgeProcessing/longterm_history/MizumotoBridgeContinuousMonitoring_longterm.jsonl ~/IoSAR-EdgeProcessing/longterm_history/MizumotoBridgeContinuousMonitoring_longterm.jsonl.pre-coord-fix`
   (entries logged since 2026-09-07 used the old, wrong target R_m — diffing across the coordinate change would silently corrupt the APS fit, not error out)
4. `sudo systemctl restart mizumoto-pipeline.service`
5. Confirm: `tail -f ~/mizumoto_pipeline.log`, wait for one full cycle, check the "PS source" / "Loaded 5 PS" line shows `PierLeft (156,899)` etc., not `(147,884)`
6. Everything logged between 2026-09-07 ~21:00 and this fix used the wrong target coordinates — treat that window's `ps_metrics.json`/InfluxDB data as using the weaker point set, not invalid, just not the final one.

## What's running now

**Two independent systemd services on the RPi (`imrsl@imrslpi5-02`), both `enabled` (autostart on boot):**

### `mizumoto-pipeline.service`
```
python3 pipeline.py --config config/mizumotobridge-100m-cfg.toml \
  --cycle-period 1800 --duration 20 --label MizumotoBridgeContinuousMonitoring \
  --ps-file /home/imrsl/ps_manual_span5.json \
  --longterm-ps-file /home/imrsl/mmwave-cli/ps_manual_longterm_7ref.json \
  --lora-phase-eval-file /home/imrsl/mmwave-cli/ps_manual_lora_phase_eval.json \
  --longterm-at-hour 3.0 --slc-export-external \
  --postproc-dir "/media/imrsl/Extreme SSD1/PostProc" --min-free-gb 10
```
- `Restart=on-failure`, `RestartSec=30`. Logs: `~/mizumoto_pipeline.log`.
- Replaces the old `BridgeSpanMonitor` label run (PID 4238, manual `nohup`, no autostart) that had been running since 2026-09-03.

### `mizumoto-slc-export.service`
```
python3 batch_slc_export.py "/media/imrsl/Extreme SSD1/PostProc" \
  ~/IoSAR-EdgeProcessing/CalibTIDEP2MizumotoBridge100m_260901_195303.mat \
  "/media/imrsl/Extreme SSD1/SLC_Export" --label MizumotoBridgeContinuousMonitoring
```
- `Restart=always`, `RestartSec=300` — idempotent, re-scans every 5 min for new captures. Decoupled from the main pipeline so Step 3b's ~900s/capture export never blocks the 1800s cycle budget. Logs: `~/mizumoto_slc_export.log`.
- Step 4b's own 2-hour anchor retry window (`ANCHOR_RETRY_WINDOW_HOURS`, `longterm_monitoring.py`) absorbs the export lag with no code changes needed.

## Code state (verified identical Mac ↔ RPi)

| Repo | Branch | HEAD |
|---|---|---|
| `mmwave-cli` | `feat/finite-num-frames` | `f935935` |
| `IoSAR-EdgeProcessing` | `continuous-monitoring-sept-2026` | `09c7cd1` |

Both pushed to origin. RPi's prior local uncommitted state (from `experiment-indoor-solar-panel`) was preserved on a new branch `experimentmizumotobridge-260903` (commit `a32d3bb`, pushed) before switching.

## What changed this session

**New feature — 12-point phase-eval, offline APS evaluation:**
- `ps_monitoring._compute_phase_eval()` — coherent-mean phase (radians) at a fixed 7-reference + 5-target point set, extracted every capture, stored in `ps_metrics.json.phase_eval`.
- `lora_sender.py` — encodes as `n_phase` (uint8, always present) + int16×1000 per point, appended before the optional trailing temp byte.
- `dashboard/ttn-uplink-formatter.js` — decodes to `n_phase`, `phase_rad_0..11`. Deliberately not wired to any Grafana panel.
- `dashboard/telegraf/telegraf.conf` — field mappings for `phase_rad_0..11`, `n_phase`, and (previously missing) `dominant_frequency_hz_2`.
- `pipeline.py` — `--lora-phase-eval-file`, `--slc-export-external` flags.

**Bugs found and fixed (pre-existing, not introduced this session):**
1. **Calibration mismatch** — `mimo_processing.py`'s `CALIB_FILE` pointed to `calibrateResults_MizumotorBridge50mTIDEP2.mat` (embedded `Slope_MHzperus=51.418`) instead of `CalibTIDEP2MizumotoBridge100m_260901_195303.mat` (`Slope_MHzperus=11.008`, the actual profile in use). `SLOPE_CALIB`/`FS_CALIB` constants were wrong for either file. **This affected every frequency/displacement number Step 4 has ever produced on this deployment.** Fixed and verified against both files' own embedded metadata via `scipy.io.loadmat`.
2. **`MIN_KEEP=8` vs 7-point reference pool** — `aps_monitoring.fit_A1_robust()`'s outlier-rejection could never trigger with only 7 references (7 < 8 always), silently disabling it. Lowered to `MIN_KEEP=5`; verified with a synthetic outlier (6/7 kept, A1 recovered near truth).
3. **Bridge target mismatch** — `ps_manual_stable_longterm.json`'s 5 targets (`pier_kiri`/`quarter_kiri`/`midspan`/`quarter_kanan`/`pier_kanan`) were a stale, different PS selection from the production `ps_manual_span5.json` (`PierRight`/`PierLeft`/`MidSpan`/`MidLeft`/`MidRight` — different angle_bin/range_bin entirely). Both `ps_manual_longterm_7ref.json` and `ps_manual_lora_phase_eval.json` now use span5's points; `R_m`/`x_m`/`y_m` derived via a verified bin→metre linear fit (residual ~1e-5 m against 12 known points): `R_m = 0.0532670*range_bin + 0.26636`, `sin_theta = 1 - angle_bin/128`.
4. **TTN Console payload formatter was severely stale** — predated per-PS support entirely (10-byte header, no `dominant_frequency_hz_2`, no per-PS/phase-eval sections). Confirmed by byte-exact replay: it decoded `n_ps=0`, `temperature_c=80` (actual 32), `displacement_rms_mm=0` (actual 0.044), `max_deflection_mm=0.044` (actual 0.080, misaligned with rms). User updated it to the current `dashboard/ttn-uplink-formatter.js`.
5. **Telegraf VPS config was stale** (missing `phase_rad_*`/`n_phase`/`dominant_frequency_hz_2` mappings) — deployed and restarted (`/opt/telegraf-iosar/`, old config backed up as `telegraf.conf.bak.*`).

**Verification:** after both fixes (TTN formatter + Telegraf), the exact same payload bytes were replayed through the real path (RPi → Wio-E5 → TTN → MQTT → Telegraf → InfluxDB) and every field decoded correctly, including all 12 `phase_rad_N` values matching `ps_metrics.json` exactly, and `dominant_frequency_hz` correctly written as a real gap (not `0`) when no peak clears the gate.

## First production cycle (post-fix)

- Cycle 1 (21:14:28): capture failed (`mimo.py exit code 2`), auto-recovered via `light_retry`.
- Cycle 2 (21:15:16): succeeded end-to-end. Step 1: 106.3s · Step 2: 243.4s · Step 4: 321.5s (3 extraction passes: 5pt main + 7pt gate-2 + 12pt phase-eval) · Step 4b: 0.0s (correctly skipped, not the 03:00 anchor) · Step 5: 55.5s (LoRa join failed once, force-rejoined, ACK confirmed). **Total: 727.1s**, well inside the 1800s budget (~18 min margin). Disk free: 1680 GB.

## Known, not yet addressed (informational, not blocking)

- Historical capture success rate on this hardware: ~48-63% (documented, recovery ladder handles it automatically — not specific to this deployment).
- `ps_manual_longterm_7ref.json`'s `R_m`/`x_m`/`y_m` for the 5 targets are derived via curve-fit, not independently verified against a real `_SLC.mat` power reading (see file's own `capture_reference` note). Worth running `tools/csv_to_ps_json.py`'s `assert_bin_mapping()` against it when convenient.
- Backfill of `BridgeSpanMonitor_*` SLC exports (Sep 3-7, pre-swap) was intentionally stopped short at user's request — not complete, not a service, one-off and abandoned.

## Contact points while disconnected

- RPi: `ssh imrsl@imrslpi5-02.local`
- Logs: `~/mizumoto_pipeline.log`, `~/mizumoto_slc_export.log`
- Service control: `sudo systemctl status|restart|stop mizumoto-pipeline.service` (same for `mizumoto-slc-export.service`)
- InfluxDB: bucket `iosar`, measurement `uplink`, device `gb-sar-01` (see `CLAUDE.md` Flux query template)
