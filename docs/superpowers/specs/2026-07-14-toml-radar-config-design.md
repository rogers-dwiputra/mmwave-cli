# TOML Radar Config for the Python Path — Design

**Date:** 2026-07-14
**Sub-project:** A (first slice) — config-driven radar capture
**Status:** Approved for planning

## Goal

Let the Python capture path (`mimo.py`, `pipeline.py`) read the per-experiment
radar configuration from a TOML file passed on the command line
(`--config PATH`), so that a new experiment with different radar parameters
needs **only a new TOML file** — never an edit to `mimo.py` or `pipeline.py`.

This removes the reason the team created a new git branch per experiment (each
of those branches differs only in the hardcoded `config_dict`).

## Context

- The active capture path is Python. The radar config it programs lives
  hardcoded in `mimo.py` `config_dict` (`mimo.profile` / `mimo.frame` /
  `mimo.channel`). `pipeline.py` imports that same dict.
- `mmwcas.mmw_set_config(configdict)` reads **only** `mimo.profile`,
  `mimo.frame` (numLoops, numFrames, framePeriodicity), and `mimo.channel`
  (rxChannelEn, txChannelEn). Per-device chirp/TDM allocation is **hardcoded
  inside `mmwcas.pyx`**, not taken from config. So the entire configurable
  surface of the Python path is those three sections.
- A separate, richer TOML schema already exists under `config/*.toml`, but it
  is consumed by the **legacy C binary** (`mimo.c`, `#include "toml/config.h"`)
  and includes C-only sections (`tx`, `chirp` per-device, `system`,
  `dataPath`, `capture`, `network`, top-level `devices`). The Python path never
  read TOML — that is why a past attempt to use it with Python failed.
- `tomllib` is in the Python 3.11+ standard library (RPi runs 3.13, Mac 3.11),
  so **no new runtime dependency** is required.

## Scope

**In scope**
- A TOML loader that merges `[mimo.profile]` / `[mimo.frame]` /
  `[mimo.channel]` over the built-in default config and returns a dict ready
  for `mmw_set_config`.
- `--config PATH` on both `mimo.py` and `pipeline.py`.
- An example experiment TOML + docs.

**Out of scope (explicitly, for later sub-projects)**
- Unified 3-mode CLI restructure (keep `mimo.py` + `pipeline.py` as they are).
- Git consolidation of the experiment branches to `main`.
- Putting run parameters (label, duration, tda-ip, cycle-period, ps-file) in
  the TOML — those stay as CLI arguments.
- Any change to edge processing (`~/IoSAR-EdgeProcessing/`), the C binary, or
  the per-device chirp/TDM allocation.

## Architecture

New module **`radar_config.py`** — standard library only, must **not** import
`mmwcas` (so it stays importable and unit-testable on any host):

```
load_and_merge(toml_path: str, base: dict) -> dict
```

- Reads and parses `toml_path` with `tomllib`.
- Deep-merges the `[mimo.profile]`, `[mimo.frame]`, `[mimo.channel]` sections
  over a **copy** of `base` (the caller's default `config_dict`). `base` is
  never mutated; the merged copy is returned.
- Merge is per-key within each section: keys present in the TOML override the
  base; keys absent from the TOML keep the base value. A section absent from
  the TOML is taken entirely from the base.
- Returns the merged `config_dict`-shaped dict.

The default `config_dict` stays in `mimo.py`; callers pass it as `base`. The
loader itself is mmwcas-free.

### Merge and validation rules

- **C-only sections ignored silently:** any of `tx`, `chirp`, `system`,
  `dataPath`, `capture`, `network` under `[mimo]`, and the top-level `devices`
  / `radar_enabled` keys, are ignored without error — so an existing
  `config/*.toml` C-side file loads cleanly (only its profile/frame are used;
  it has no `[mimo.channel]`, so channel falls back to the base default).
- **Unknown key inside `profile`/`frame`/`channel` → hard error** listing the
  offending key(s), with a hint of the valid keys. Rationale: a typo in a
  radar parameter (e.g. `numAdcSample`) must fail loudly, not be silently
  dropped and ruin an experiment.
- **Missing file / parse error → clear message, non-zero exit.** All of this
  happens before any hardware is touched, so a bad config never disturbs the
  radar or the recovery ladder.
- Light type checking only: known numeric fields must be numbers. Radar-physics
  validity (slope/bandwidth/range limits) is left to `mmwcas`/hardware — not the
  loader's job.

## Data flow (wiring)

`--config PATH` is optional on both entry points. **Without `--config`, behavior
is byte-for-byte identical to today** (the hardcoded default `config_dict`).

**`mimo.py`** (standalone, and spawned by pipeline default mode):
- In `main()`, after arg parsing: if `--config` is set,
  `cfg = radar_config.load_and_merge(args.config, base=config_dict)`; use `cfg`
  for both `mmw_set_config` and `export_config_to_json`. Follows the existing
  pattern where `main()` already adjusts the config for `--finite-framing`.
- `--finite-framing` composes: `numFrames` is computed from the **merged**
  `framePeriodicity` (so a TOML that changes the frame period is respected).

**`pipeline.py`** (two modes):
- **Default mode:** `run_capture()` simply **forwards** `--config <path>` to the
  `mimo.py` subprocess (exactly as it forwards `--finite-framing`). mimo.py does
  the merge; pipeline.py never parses the TOML.
- **Persistent mode:** `init_radar()` performs the merge itself (it calls
  `mmw_set_config` directly), and the same merged config is used by
  `capture_once()` for `export_config_to_json`, so the saved `.mmwave.json`
  matches the effective config.
- `--config` is validated early in `main()` (alongside the existing
  `--finite-framing` validation), so a bad path/TOML exits cleanly before the
  hardware/ladder is touched. Validation that needs `mmwcas` (via
  `from mimo import config_dict`) is guarded the same way `--finite-framing`
  validation already is, so `pipeline.py` stays importable without `mmwcas`.

### Reproducibility

The **effective** (merged) config is exported to `.mmwave.json` every capture,
exactly as today via `export_config_to_json`. So every capture is reproducible
from its own JSON even when the source TOML is minimal.

## Config file location

Experiment TOML files live in the existing `config/` directory. The Python
loader ignores C-only sections, so existing `config/*.toml` files load under the
Python path (using their profile/frame; channel defaults from base). Note the two
schemas are not fully interchangeable in the other direction — a Python-oriented
file (profile/frame/channel only) lacks the `chirp` section the C binary needs.

## Testing

**Unit — `tests/test_radar_config.py`** (Mac, stdlib, no hardware):
- partial merge: a TOML setting a few `profile`/`frame` fields overrides only
  those; all other fields inherit `base`.
- full override: a TOML specifying a whole section replaces those keys.
- C-only sections (`[mimo.tx]`, `[mimo.chirp]`, …) present → loaded without
  error and ignored.
- unknown key inside `[mimo.profile]` → raises a clear error.
- missing file → error; malformed TOML → error.
- `base` is not mutated (loader returns a copy).

**Wiring:** `python3 -m py_compile mimo.py pipeline.py radar_config.py`;
`python3 -c "import pipeline"` still succeeds on the Mac (radar_config is
stdlib, safe to import at module level).

**Hardware (RPi):** `python3 mimo.py --config config/<test>.toml -t 5
--directory CfgTest` → confirm the exported `.mmwave.json` reflects the TOML
values (e.g. changed `numAdcSamples` / `frequencySlope`). Plus one
`pipeline.py --persistent --config …` run.

## Deliverables

- `radar_config.py` (new)
- `tests/test_radar_config.py` (new)
- `mimo.py`, `pipeline.py` — add `--config`
- `config/example-experiment.toml` (new) — minimal merge-style example with
  comments, doubling as documentation
- `CLAUDE.md` — document `--config` and the TOML config workflow

## Backward compatibility

No `--config` → the hardcoded default `config_dict` is used and every existing
invocation behaves exactly as before. This is a hard requirement (matches the
reliability branch's regression constraint).
