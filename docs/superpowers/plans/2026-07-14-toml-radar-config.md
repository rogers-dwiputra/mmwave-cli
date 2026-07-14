# TOML Radar Config (Python Path `--config`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `mimo.py` and `pipeline.py` load per-experiment radar config from a TOML file (`--config PATH`) so a new experiment needs only a new TOML file, never a code edit.

**Architecture:** A new stdlib-only module `radar_config.py` reads a TOML file and deep-merges its `[mimo.profile]`/`[mimo.frame]`/`[mimo.channel]` sections over the built-in default `config_dict`, returning a merged dict for `mmw_set_config`. Both entry points gain `--config`; in pipeline default mode the flag is forwarded to the `mimo.py` subprocess, in persistent mode the merge happens in-process.

**Tech Stack:** Python 3.11+ (`tomllib` stdlib), pytest (dev-only). No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-07-14-toml-radar-config-design.md`

## Global Constraints

- `radar_config.py` MUST be stdlib-only and MUST NOT import `mmwcas` — it stays importable and unit-testable on any host.
- No new runtime dependency. `tomllib` is stdlib on Python 3.11+ (Mac 3.11, RPi 3.13).
- With no `--config`, behavior MUST be byte-for-byte identical to current (regression constraint).
- Only `[mimo.profile]`, `[mimo.frame]`, `[mimo.channel]` are honored. C-binary-only sections (`tx`, `chirp`, `system`, `dataPath`, `capture`, `network`) and top-level `devices`/`radar_enabled` are ignored without error. An unknown key **inside** a honored section is a hard error (typo protection). A non-numeric value for a honored key is a hard error.
- `base` passed to the loader MUST NOT be mutated; the loader returns a deep copy.
- Hardware verification (`--config` against the real radar) runs only on the Raspberry Pi (`ssh imrsl@imrslpi5-02`, password `imrsl2022`; then `cd ~/mmwave-cli`). All pure-Python tests must pass on the Mac. The RPi runs these steps via the branch pushed to the `rpi` remote.
- Work happens on branch `feat/toml-config`, created from `feat/reliability`.

**One-time setup before Task 1:**

```bash
cd /Users/mac/Documents/Projects/mmwave-cli
git checkout feat/reliability
git checkout -b feat/toml-config
python3 -m pytest tests/ -q   # sanity: existing suite green
```

## File Structure

- Create `radar_config.py` — the TOML load + merge + validation. One responsibility.
- Create `tests/test_radar_config.py` — unit tests for the loader (Mac, stdlib).
- Create `config/example-experiment.toml` — minimal merge-style example / doc.
- Modify `mimo.py` — add `--config`, use the merged config in `main()`.
- Modify `pipeline.py` — add `--config`, forward in default mode, merge in persistent mode.
- Modify `CLAUDE.md` — document the workflow.

---

### Task 1: `radar_config.py` — TOML load + merge + validation

**Files:**
- Create: `radar_config.py`
- Test: `tests/test_radar_config.py`

**Interfaces:**
- Consumes: nothing (stdlib `tomllib`, `copy`).
- Produces (used by Tasks 2–3):
  - `radar_config.load_and_merge(toml_path: str, base: dict) -> dict` — returns a deep-merged copy of `base`; raises `FileNotFoundError` (missing file), `tomllib.TOMLDecodeError` (bad TOML), or `ValueError` (unknown key / non-numeric value in a honored section).

- [ ] **Step 1: Write the failing tests**

`tests/test_radar_config.py`:

```python
import copy

import pytest

import radar_config

BASE = {
    'mimo': {
        'profile': {'id': 0, 'startFrequency': 77, 'frequencySlope': 90,
                    'idleTime': 3.5, 'adcStartTime': 4.45, 'numAdcSamples': 120,
                    'adcSamplingFrequency': 6500, 'rampEndTime': 23.65,
                    'rxGain': 48, 'txStartTime': 0,
                    'hpfCornerFreq1': 0, 'hpfCornerFreq2': 0},
        'frame': {'numLoops': 10, 'numFrames': 0, 'framePeriodicity': 30},
        'channel': {'rxChannelEn': 0x0F, 'txChannelEn': 0x07},
    }
}


def _write(tmp_path, text):
    p = tmp_path / 'exp.toml'
    p.write_text(text)
    return str(p)


def test_partial_merge_overrides_only_specified(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nfrequencySlope = 65.854\nnumAdcSamples = 512\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['profile']['frequencySlope'] == 65.854
    assert cfg['mimo']['profile']['numAdcSamples'] == 512
    assert cfg['mimo']['profile']['startFrequency'] == 77      # inherited
    assert cfg['mimo']['frame']['framePeriodicity'] == 30      # inherited


def test_frame_and_channel_merge(tmp_path):
    path = _write(tmp_path,
                  '[mimo.frame]\nframePeriodicity = 50\nnumLoops = 16\n'
                  '[mimo.channel]\ntxChannelEn = 0x01\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['frame']['framePeriodicity'] == 50
    assert cfg['mimo']['frame']['numLoops'] == 16
    assert cfg['mimo']['channel']['txChannelEn'] == 1
    assert cfg['mimo']['channel']['rxChannelEn'] == 0x0F       # inherited


def test_c_only_sections_ignored(tmp_path):
    path = _write(tmp_path,
                  '[mimo.profile]\nnumAdcSamples = 256\n\n'
                  '[mimo.tx]\ntx0PhaseShifter = 3\n\n'
                  '[mimo.chirp]\nstartIdx = 0\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['profile']['numAdcSamples'] == 256
    assert 'tx' not in cfg['mimo']
    assert 'chirp' not in cfg['mimo']


def test_unknown_key_in_profile_errors(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSample = 512\n')   # typo
    with pytest.raises(ValueError, match='numAdcSample'):
        radar_config.load_and_merge(path, BASE)


def test_non_numeric_value_errors(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSamples = "512"\n')
    with pytest.raises(ValueError, match='numAdcSamples'):
        radar_config.load_and_merge(path, BASE)


def test_missing_file_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        radar_config.load_and_merge(str(tmp_path / 'nope.toml'), BASE)


def test_malformed_toml_errors(tmp_path):
    import tomllib
    path = _write(tmp_path, '[mimo.profile\nnumAdcSamples = 512')
    with pytest.raises(tomllib.TOMLDecodeError):
        radar_config.load_and_merge(path, BASE)


def test_base_not_mutated(tmp_path):
    snapshot = copy.deepcopy(BASE)
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSamples = 999\n')
    radar_config.load_and_merge(path, BASE)
    assert BASE == snapshot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mac/Documents/Projects/mmwave-cli && python3 -m pytest tests/test_radar_config.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'radar_config'`

- [ ] **Step 3: Write the implementation**

`radar_config.py`:

```python
#!/usr/bin/env python3
"""
Load a per-experiment radar config from a TOML file and merge it over the
built-in default config_dict.

Only the sections mmwcas.mmw_set_config() reads are honored:
  [mimo.profile], [mimo.frame], [mimo.channel]
C-binary-only sections (tx, chirp, system, dataPath, capture, network) and the
top-level devices/radar_enabled keys are ignored, so an existing config/*.toml
file written for the C binary still loads (only its profile/frame are used).

Stdlib only (tomllib, Python 3.11+). Never imports mmwcas — importable and
unit-testable on any host.
"""
import copy
import tomllib

# Sections under [mimo] the Python path programs (mmwcas reads these).
_MERGE_SECTIONS = ('profile', 'frame', 'channel')


def load_and_merge(toml_path, base):
    """
    Read `toml_path`, merge its [mimo.profile]/[mimo.frame]/[mimo.channel]
    sections over a deep copy of `base`, and return the merged config dict.

    `base` is not mutated. Unknown keys inside a honored section, or a
    non-numeric value for a honored key, raise ValueError (typo/type
    protection). A missing file raises FileNotFoundError; malformed TOML raises
    tomllib.TOMLDecodeError.
    """
    with open(toml_path, 'rb') as fh:
        data = tomllib.load(fh)

    merged = copy.deepcopy(base)
    mimo = data.get('mimo', {})

    for section in _MERGE_SECTIONS:
        if section not in mimo:
            continue
        overrides = mimo[section]
        if not isinstance(overrides, dict):
            raise ValueError(
                f'[mimo.{section}] must be a table, got {type(overrides).__name__}')
        valid = merged['mimo'][section]
        unknown = sorted(k for k in overrides if k not in valid)
        if unknown:
            raise ValueError(
                f'Unknown key(s) in [mimo.{section}]: {", ".join(unknown)}. '
                f'Valid keys: {", ".join(sorted(valid))}')
        for key, value in overrides.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f'[mimo.{section}].{key} must be a number, '
                    f'got {type(value).__name__}')
            merged['mimo'][section][key] = value

    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_radar_config.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add radar_config.py tests/test_radar_config.py
git commit -m "feat(config): TOML radar-config loader (merge profile/frame/channel over default)"
```

---

### Task 2: `mimo.py` — `--config` flag + example TOML

**Files:**
- Modify: `mimo.py` (argparse; `main()` config resolution + use `cfg` in place of `config_dict`)
- Create: `config/example-experiment.toml`

**Interfaces:**
- Consumes: `radar_config.load_and_merge(toml_path, base)` (Task 1); module-global `config_dict`.
- Produces: `mimo.py --config PATH` merges the TOML over `config_dict` before configuring the radar. CLI unchanged when `--config` is absent.

- [ ] **Step 1: Add the `--config` argument**

In `mimo.py`, add after the `--finite-framing` argument (immediately before `args = parser.parse_args()`):

```python
    parser.add_argument('--config', type=str, default=None,
                        help='Radar-config TOML. Merges [mimo.profile]/[mimo.frame]/'
                             '[mimo.channel] over the built-in default (config_dict). '
                             'Without it, the built-in default is used.')
```

- [ ] **Step 2: Resolve the config in `main()`**

In `mimo.py`, immediately after the `--num-loops` validation block
(`if args.num_loops < 0: ... sys.exit(1)`), insert:

```python
    # Resolve radar config: merged TOML if --config given, else the default.
    cfg = config_dict
    if args.config:
        import radar_config
        try:
            cfg = radar_config.load_and_merge(args.config, config_dict)
        except (FileNotFoundError, ValueError) as exc:
            print(f"--config: {exc}")
            sys.exit(2)
        except Exception as exc:                      # tomllib.TOMLDecodeError, etc.
            print(f"--config: failed to parse {args.config}: {exc}")
            sys.exit(2)
        print(f"Loaded radar config: {args.config}")
```

- [ ] **Step 3: Use `cfg` in place of `config_dict` in `main()`**

Make these four replacements in `main()` (they currently read `config_dict`):

1. finite-framing period read:
   `fp = config_dict["mimo"]["frame"]["framePeriodicity"]`
   → `fp = cfg["mimo"]["frame"]["framePeriodicity"]`
2. finite-framing numFrames write:
   `config_dict["mimo"]["frame"]["numFrames"] = nf`
   → `cfg["mimo"]["frame"]["numFrames"] = nf`
3. configure call:
   `status = mmwcas.mmw_set_config(config_dict)`
   → `status = mmwcas.mmw_set_config(cfg)`
4. JSON export in the capture loop:
   `export_config_to_json(config_dict, json_filename)`
   → `export_config_to_json(cfg, json_filename)`

(The module-global `config_dict` definition stays — it is the default and the
merge base, and `pipeline.py` still imports it.)

- [ ] **Step 4: Create the example TOML**

`config/example-experiment.toml`:

```toml
# Example experiment radar config for the Python capture path.
#
# Only [mimo.profile] / [mimo.frame] / [mimo.channel] are read. List ONLY the
# fields that differ from the built-in default (config_dict in mimo.py) —
# everything else is inherited. The effective (merged) config is written to the
# capture's .mmwave.json, so every capture is reproducible.
#
#   python3 mimo.py --config config/example-experiment.toml -t 5 --directory MyExp
#   python3 pipeline.py --persistent --config config/example-experiment.toml ...

[mimo.profile]
frequencySlope = 65.854    # MHz/us  (wider sweep than the 90 default)
numAdcSamples  = 256

[mimo.frame]
framePeriodicity = 50      # ms  -> 20 Hz frame rate
```

- [ ] **Step 5: Mac-side sanity + commit**

Run: `python3 -m pytest tests/ -q` (unchanged — nothing imports mmwcas)
Run: `python3 -m py_compile mimo.py`
Expected: no output (compile OK)

```bash
git add mimo.py config/example-experiment.toml
git commit -m "feat(mimo): --config loads a TOML radar config (merged over default)"
```

- [ ] **Step 6: Verify on the Raspberry Pi**

```bash
ssh imrsl@imrslpi5-02        # password: imrsl2022
cd ~/mmwave-cli && git fetch && git checkout feat/toml-config && git pull
# Wrong path must fail cleanly (exit 2), before touching hardware:
python3 mimo.py --config config/does-not-exist.toml -t 1; echo "exit=$?"
# Expected: "--config: ..." then exit=2
# Real capture with the example config:
python3 mimo.py --config config/example-experiment.toml -t 5 --directory CfgTest; echo "exit=$?"
# Expected: capture completes, exit=0
# The exported JSON must reflect the TOML values:
python3 -c "import json,glob; f=sorted(glob.glob('mmwave_json_files/CfgTest_*.mmwave.json'))[-1]; d=json.load(open(f)); print(f); print(d['mimo']['profile']['frequencySlope'], d['mimo']['profile']['numAdcSamples'], d['mimo']['frame']['framePeriodicity'])"
# Expected: 65.854 256 50
```

---

### Task 3: `pipeline.py` — `--config` (forward in default mode, merge in persistent)

**Files:**
- Modify: `pipeline.py` (argparse; early file check; `run_capture`, `init_radar`, `reinit_radar`, `capture_once` signatures + call sites; persistent-mode config load; banner)

**Interfaces:**
- Consumes: `radar_config.load_and_merge` (Task 1); `mimo.config_dict`; the `--config` flag on `mimo.py` (Task 2, used by default-mode forwarding).
- Produces: `pipeline.py --config PATH`. Default mode forwards `--config` to the `mimo.py` subprocess; persistent mode merges in-process and uses the merged config for both `mmw_set_config` and the `.mmwave.json` export.

- [ ] **Step 1: Add the `--config` argument**

In `pipeline.py`, add after the `--finite-framing` argument (immediately before `args = parser.parse_args()`):

```python
    parser.add_argument('--config', type=str, default=None,
                        help='Radar-config TOML (merges [mimo.profile]/[mimo.frame]/'
                             '[mimo.channel] over the built-in default). Forwarded to '
                             'mimo.py in default mode; merged in-process in --persistent.')
```

- [ ] **Step 2: Early file-existence check**

In `main()`, right after the `--finite-framing` validation block (the
`if args.finite_framing:` try/except that ends with `parser.error(...)`), insert:

```python
    if args.config and not os.path.isfile(args.config):
        parser.error(f'--config: file not found: {args.config}')
```

- [ ] **Step 3: Forward `--config` in default-mode `run_capture`**

Change the signature:

```python
def run_capture(duration: float, tda_ip: str, label: str,
                finite_framing: bool = False, config_path: str = None) -> str | None:
```

and after the existing `if finite_framing: cmd.append('--finite-framing')` block, add:

```python
    if config_path:
        cmd += ['--config', config_path]
```

- [ ] **Step 4: Thread `config` through the persistent-mode functions**

`init_radar` — change the signature and the config source:

```python
def init_radar(tda_ip: str, duration: float = None, finite_framing: bool = False,
               config: dict = None) -> bool:
    """Heavy phase, done once per process: TDA connect → power-up → firmware
    → RF init calibration → frame config."""
    import mmwcas
    if config is None:
        from mimo import config_dict as config
```

(Delete the old `from mimo import config_dict` line. In the body, the
finite-framing block and `mmw_set_config` already reference `config_dict`;
rename those two references to `config`:
`fp = config['mimo']['frame']['framePeriodicity']`,
`config['mimo']['frame']['numFrames'] = finite_num_frames(duration, fp)`,
`status = mmwcas.mmw_set_config(config)`.)

`reinit_radar` — pass `config` through:

```python
def reinit_radar(tda_ip: str, duration: float = None, finite_framing: bool = False,
                 config: dict = None) -> bool:
    """Ladder software_reinit rung: power off (best effort) then full re-init
    (spec §1b). Re-initing a still-powered radar is the -8 scenario."""
    import mmwcas
    if hasattr(mmwcas, 'mmw_power_off'):
        try:
            mmwcas.mmw_power_off()
        except Exception as exc:
            print(f'[PIPELINE] WARNING: power-off before reinit failed: {exc}')
    return init_radar(tda_ip, duration, finite_framing, config)
```

`capture_once` — change the signature and the config source (used for export):

```python
def capture_once(duration: float, tda_ip: str, label: str,
                 finite_framing: bool = False, config: dict = None) -> str | None:
    """One capture WITHOUT re-init (arm → frame → stop → dearm).
    Returns capture directory name, or None on failure."""
    import mmwcas
    if config is None:
        from mimo import config_dict as config
    from utility import check_captured_files, export_config_to_json
```

(Delete the old `from mimo import config_dict` line. Change the export call at
the end from `export_config_to_json(config_dict, json_path)` to
`export_config_to_json(config, json_path)`.)

- [ ] **Step 5: Load the merged config once and wire the call sites**

In `main()`, immediately before the `reinit_fn = ...` line, insert:

```python
    radar_cfg = None
    if args.persistent and args.config:
        import radar_config
        from mimo import config_dict
        try:
            radar_cfg = radar_config.load_and_merge(args.config, config_dict)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(f'--config: {exc}')
        except Exception as exc:                       # tomllib.TOMLDecodeError, etc.
            parser.error(f'--config: failed to parse {args.config}: {exc}')
```

Then update the three persistent call sites to pass `radar_cfg`, and the
default call site to pass `args.config`:

- `reinit_fn`:
  `reinit_fn = (lambda: reinit_radar(args.tda_ip, args.duration, args.finite_framing, radar_cfg)) if args.persistent else None`
- startup init loop:
  `while not shutdown_flag and not init_radar(args.tda_ip, args.duration, args.finite_framing, radar_cfg):`
- cycle-loop capture:
  ```python
        if args.persistent:
            capture_dir = capture_once(args.duration, args.tda_ip, args.label, args.finite_framing, radar_cfg)
        else:
            capture_dir = run_capture(args.duration, args.tda_ip, args.label, args.finite_framing, args.config)
  ```

- [ ] **Step 6: Add a banner line**

In the startup banner block (near `print(f'  Capture mode ...')`), add:

```python
    if args.config:
        print(f'  Radar config     : {args.config} (merged over default)')
```

- [ ] **Step 7: Mac-side sanity + commit**

Run: `python3 -m pytest tests/ -q` (unchanged)
Run: `python3 -m py_compile pipeline.py`
Run: `python3 -c "import pipeline; print('pipeline importable without mmwcas')"`
Expected: all OK — the `radar_config` import inside `main()` is lazy, and
`pipeline` still imports without `mmwcas`.

```bash
git add pipeline.py
git commit -m "feat(pipeline): --config (forward in default mode, merge in persistent)"
```

- [ ] **Step 8: Verify on the Raspberry Pi**

```bash
ssh imrsl@imrslpi5-02
cd ~/mmwave-cli && git pull
# Persistent mode with the example config; confirm banner + a capture + JSON:
python3 pipeline.py --persistent --config config/example-experiment.toml \
    --duration 5 --label CfgPersist --skip-transfer --skip-ps --skip-lora &
sleep 140; kill -INT %1; wait
python3 -c "import json,glob; f=sorted(glob.glob('mmwave_json_files/CfgPersist_*.mmwave.json'))[-1]; d=json.load(open(f)); print(d['mimo']['profile']['numAdcSamples'], d['mimo']['frame']['framePeriodicity'])"
# Expected: 256 50   (values from the TOML, proving the persistent-mode merge)
# Cleanup: remove CfgPersist_* / CfgTest_* dirs from the TDA /mnt/ssd.
```

---

### Task 4: Documentation

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `CLAUDE.md`**

1. **Repository Structure** — add under `pipeline.py` (or near `utility.py`):

```
├── radar_config.py                 ← load + merge experiment TOML config (--config)
```

2. **Common invocations** — add:

```bash
# Run an experiment from a TOML config (no code edits per experiment)
python3 mimo.py --config config/example-experiment.toml -t 30 --directory MyExp
python3 pipeline.py --persistent --config config/experiment.toml --duration 30 --label MyExp
```

3. **Key pipeline arguments table** — add a row:

```
| `--config` | None | Radar-config TOML: merges `[mimo.profile]`/`[mimo.frame]`/`[mimo.channel]` over the built-in default. Forwarded to mimo.py in default mode; merged in-process in `--persistent`. |
```

4. Add a short subsection after the pipeline arguments table:

```markdown
### Experiment configs (TOML)

Different radar configurations no longer require editing `config_dict` in
`mimo.py`. Put the fields that differ from the default in a TOML file and pass
`--config path.toml` to `mimo.py` or `pipeline.py`:

- Only `[mimo.profile]`, `[mimo.frame]`, `[mimo.channel]` are read (the fields
  `mmwcas.mmw_set_config` programs). List only what changes — the rest is
  inherited from the built-in default.
- C-binary-only sections (`tx`, `chirp`, …) in existing `config/*.toml` are
  ignored, so those files still load under the Python path.
- A typo'd key inside a honored section is a hard error (protects experiments).
- The effective merged config is exported to each capture's `.mmwave.json`.

See `config/example-experiment.toml`.
```

- [ ] **Step 2: Final check + commit**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

```bash
git add CLAUDE.md
git commit -m "docs: document TOML experiment configs (--config)"
```

---

## Self-Review Notes

- Spec coverage: architecture/module → Task 1; merge & validation rules → Task 1 (tests) ; mimo.py wiring → Task 2; pipeline.py forward+merge → Task 3; config location `config/` + example → Task 2; reproducibility (.mmwave.json export) → Tasks 2–3 (uses `cfg`/`config`); testing → Task 1 unit + Tasks 2–3 RPi; deliverables → Tasks 1–4; backward compatibility → default `cfg = config_dict` path in Task 2 and `radar_cfg=None`/forward in Task 3.
- Interface names consistent across tasks: `radar_config.load_and_merge(toml_path, base)`; `run_capture(..., config_path=None)`; `init_radar/reinit_radar/capture_once(..., config=None)`.
- Deviation from a naive design (intentional): the loader validates only that honored keys are numeric; radar-physics validity is left to `mmwcas`/hardware, per the spec.
