# Design: Reliability — TDA Recovery Ladder + LoRa Store-and-Forward Queue

**Date:** 2026-07-04
**Sub-project:** B (Reliability) of the mmwave-cli improvement roadmap
**Branch:** `feat/reliability` (branched from `feat/persistent-pipeline-timestamps`)

## Context

The improvement roadmap was decomposed into four sub-projects:

- **A** — Branch consolidation + unified CLI (capture-only / continuous-capture / full-pipeline modes)
- **B** — Reliability: TDA error recovery + LoRa store-and-forward queue *(this spec)*
- **C** — GUI for PS point selection, SLC preview, zoom, crop
- **D** — Data products: cropped SLC stack storage on edge + representative SLC for APS compensation

B was chosen first because it is the most operationally urgent: field logs show up to
~48% capture failure rate (log 20260510: 12 failed of 25 cycles), and LoRa uplinks are
silently lost whenever the modem or gateway is down.

### TDA error findings (from experiment logs + TIDEP-01012.md)

- **STATUS -8** at `rfInit`/`rfEnable` (async-event timeout waiting for AWR2243) is the
  dominant error. Root cause is architectural (TIDEP-01012.md §7.2): `pipeline.py`
  spawns a fresh `mimo.py` every cycle, repeating the full heavy init (firmware
  download + RF power-up + calibration) — 3 chances per cycle to hit -8, plus
  ~85–95 s overhead.
- **Init-stage errors are fatal today**: `check()` in `mmwcas.pyx` calls
  `exit(status)` for all init stages (`mmwcas.pyx:440-474`), killing the Python
  process (exit code 248) with no cleanup, leaving the AWR2243 half-configured for
  the next attempt.
- **STATUS -1** (TDA connect, port 5001): `apps.out` busy-loop consumes CPU on the
  TDA; a full TDA rootfs (accumulated `Trace_TDA_*.txt`) once caused 40 minutes of
  total failure (162 consecutive -1) — TIDEP-01012.md §10, §11.
- **STATUS -2** (stop frame): caused by `numFrames=0` (infinite framing) + manual
  StopFrame; TI's official Lua workflow uses finite framing (TIDEP-01012.md §9).
- `pipeline-persistent.py` (init-once architecture) exists but is not yet
  field-validated.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Backlog send order on link recovery | Send all, oldest-first |
| Delivery failure detection | Confirmed uplink (`AT+CMSGHEX`, TTN ACK) |
| Remote TDA power-cycle hardware | None yet; relay planned — design includes a hook |
| Pipeline architecture | Both: init-once via `--persistent` flag; default remains spawn-per-cycle until persistent is field-validated |
| Approach | T2 (recovery ladder + pre-flight) + L1 (file spool drained by pipeline, no daemon) |

## Part 1 — TDA Reliability

### 1a. Remove fatal `exit()` from `mmwcas.pyx`

`check()` never calls `exit(status)`; all errors (including init stages) return their
status code to Python. `mmw_init` returns an error code the caller can handle.
Requires `make build` on the RPi after the change.

### 1b. New module `tda_recovery.py`

Shared by both pipeline architectures; also usable standalone for manual recovery.

**Pre-flight check** (before every cycle):
- TCP probe of TDA port 5001 (reachable = proceed).
- Via SSH: check TDA rootfs free space; when free space is below 200 MB,
  auto-delete oldest `Trace_TDA_*.txt` files until above the threshold.

**Recovery ladder** (on capture failure, escalate automatically):
1. **Light retry** — backoff 5 s → 15 s → 45 s (max 3 attempts). In persistent
   mode: re-attempt arm→frame. In default mode: re-run `mimo.py`.
2. **Software re-init** — `mmw_power_off()` → full re-init (max 2 attempts).
   Persistent mode only; default mode already re-inits on every spawn, so it
   escalates directly from level 1 to level 3.
3. **TDA reboot via SSH** — then wait for port 5001 to come back (timeout ~3 min).
4. **Relay power-cycle hook** — configurable shell command (`--power-cycle-cmd`);
   disabled by default until the relay hardware is installed.

If the entire ladder fails: sleep 10 minutes, restart the ladder from level 1.
**The pipeline never crashes** — it retries indefinitely until Ctrl+C/SIGTERM.

### 1c. `pipeline.py` integration

- New flag `--persistent`: initialize the radar once at process start; each cycle is
  only arm→frame→stop→dearm. Absorbs the logic of `pipeline-persistent.py`, which is
  then **deleted** to avoid duplication.
- Default (no flag) keeps the current spawn-`mimo.py`-per-cycle architecture until
  persistent mode is field-validated.
- Both modes use the same pre-flight + recovery ladder.

### 1d. `mimo.py` (capture-only mode)

Stays simple: light retry with backoff for failed arm/frame (no full ladder), plus
the existing `powerOff` teardown. CLI behavior unchanged.

### 1e. Observability

- Every recovery event logged with timestamp + ladder level to a structured
  `recovery_log.jsonl`.
- Per-cycle summary (success/failure/recovery level used) so error-rate improvement
  can be measured objectively against the 20260510 baseline (~48% failure).

### 1f. Optional: finite framing

New flag `--finite-framing` (default off): compute `numFrames` from duration
(duration / framePeriodicity) as in TI's official workflow, eliminating -2
stop-frame errors. Off by default because it changes framing behavior.

## Part 2 — LoRa Store-and-Forward Queue

### 2a. New module `lora_queue.py`

File-based spool at `~/lora_queue/`:

- **Enqueue**: after Step 4, copy the payload-relevant fields (unix timestamp,
  `dominant_frequency_hz`, `displacement_rms_mm`, `max_deflection_mm`) into
  `~/lora_queue/pending/<capture_dir>.json`. Capture dir names embed the timestamp,
  so alphabetical order = chronological order.
- **Drain**: join the network once, then send pending files **oldest-first**:
  - ACK received → move file to `~/lora_queue/sent/` (keep the most recent 200 as
    an audit trail; auto-delete older ones).
  - No ACK → **stop draining** (link considered down); everything remaining stays
    in `pending/` for the next cycle.
- **Per-drain limits**: max 20 uplinks per cycle, 10 s spacing between uplinks
  (AS923 duty cycle). A long backlog drains over a few cycles.
- Plain files → survives reboot/power loss; inspectable via SSH
  (`ls ~/lora_queue/pending/`).

### 2b. `lora_sender.py`

Add `send_confirmed()` using `AT+CMSGHEX`, waiting for `+CMSGHEX: ACK Received`.
The existing unconfirmed path remains for testing. Confirmed is the pipeline default.

### 2c. `pipeline.py` Step 5

Becomes: enqueue this cycle's metrics → drain the queue. Drain failure never stops
the pipeline (data is safe in the spool). `--skip-lora` still enqueues (data
accumulates); only sending is skipped — so when a modem is attached later, the
backlog transmits immediately.

### 2d. TTN note

At 15-min cadence, confirmed uplinks ≈ 96 ACK downlinks/day. The tenant
`imrsl.as1.cloud.thethings.industries` is The Things Industries (paid), so the
public-TTN Fair Use Policy (10 downlinks/day) does not apply. If the deployment
ever moves to public TTN, set `confirmed=false` or use a hybrid heartbeat mode.

## Part 3 — Error Handling, Testing, Rollout

### 3a. Error-handling principle

The pipeline never crashes on a single-step failure: capture failure → recovery
ladder; transfer failure → retry with backoff (current behavior kept); LoRa failure
→ data stays in the spool. The only exits are Ctrl+C/SIGTERM (graceful, as today).

### 3b. Testing (lab, before deployment)

- **LoRa queue**: gateway off / antenna detached → run several cycles → verify files
  accumulate in `pending/` → gateway on → verify oldest-first drain and historically
  correct points in Grafana (original timestamps preserved). Small unit tests for
  payload encoding + spool ordering (run on Mac, no hardware needed).
- **TDA recovery**: manually trigger each ladder level — unplug TDA Ethernet while
  idle (pre-flight must hold the cycle), fill TDA rootfs with dummy files
  (auto-cleanup must trigger), and run an overnight session to compare error rate
  against the 48% baseline (log 20260510).
- **Regression**: without any new flags, behavior must match today's exactly.

### 3c. Files touched

| File | Change |
|---|---|
| `mmwcas.pyx` | remove `exit(status)`; all errors return to Python |
| `tda_recovery.py` | **new** — pre-flight + recovery ladder |
| `lora_queue.py` | **new** — spool enqueue/drain |
| `lora_sender.py` | add `send_confirmed()` (AT+CMSGHEX) |
| `pipeline.py` | `--persistent` flag, recovery + queue integration |
| `pipeline-persistent.py` | **deleted** (logic absorbed into pipeline.py) |
| `mimo.py` | light retry with backoff on arm/frame |
| `CLAUDE.md` | document new flags & architecture |

### 3d. Out of scope for B

Full branch consolidation (A), PS-selection GUI (C), SLC stack storage & APS
representative SLC (D).
