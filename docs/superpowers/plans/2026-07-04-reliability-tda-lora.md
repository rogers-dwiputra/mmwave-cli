# Reliability (TDA Recovery Ladder + LoRa Store-and-Forward Queue) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the radar pipeline survive TDA/TIDEP failures via an escalating recovery ladder, and never lose LoRa uplinks via a file-based store-and-forward queue with confirmed delivery.

**Architecture:** Two new hardware-agnostic modules (`lora_queue.py` file spool, `tda_recovery.py` pre-flight + recovery ladder) with all I/O injected for testability; `mmwcas.pyx` loses its fatal `exit()` so Python owns error handling; `pipeline.py` absorbs `pipeline-persistent.py` behind a `--persistent` flag and wires in preflight, ladder, and queue drain.

**Tech Stack:** Python 3.11, pyserial (existing), Cython extension `mmwcas` (existing, RPi-only), pytest (dev-only).

**Spec:** `docs/superpowers/specs/2026-07-04-reliability-tda-lora-design.md`

## Global Constraints

- New modules `lora_queue.py` and `tda_recovery.py` MUST NOT import `mmwcas` at module level — they must be importable on a machine without the compiled extension or hardware.
- No new runtime dependencies. `pyserial` is already required. `pytest` is dev-only.
- Default behavior with no new flags must be identical to current behavior (regression constraint, spec §3b).
- Spool layout: `~/lora_queue/{pending,sent,failed}/`; keep newest **200** in `sent/`; drain max **20** uplinks per cycle with **10 s** spacing (spec §2a).
- Confirmed uplink = `AT+CMSGHEX`, success only on a line containing `ACK Received` (spec §2b).
- Recovery ladder: light retry backoff **5/15/45 s** (3 attempts) → software re-init ×2 (persistent mode only) → TDA reboot via SSH (wait ≤ **180 s** for board + **20 s** grace) → optional power-cycle command → on exhaustion sleep **600 s** and restart ladder (spec §1b).
- TDA pre-flight: SSH check that `apps.out` runs and rootfs free ≥ **200 MB**; trace files live in `/opt/vision_sdk/Trace_TDA_*.txt`, cleanup keeps the newest **20** (spec §1b; TIDEP-01012.md §11).
- Recovery events append JSON lines to `recovery_log.jsonl` next to `pipeline.py` (spec §1e).
- All Wio-E5 interaction goes through the existing `_send_at()` helper in `lora_sender.py`.
- Cython note: the `.pyx` rebuild (`make build`) and any hardware verification can only run on the Raspberry Pi (`ssh imrsl@imrslpi5-02`, password `imrsl2022`). All pure-Python tests must pass on the Mac.
- Work happens on branch `feat/reliability`, created from `feat/persistent-pipeline-timestamps`.

**One-time setup before Task 1:**

```bash
cd /Users/mac/Documents/Projects/mmwave-cli
git checkout feat/persistent-pipeline-timestamps
git checkout -b feat/reliability
pip3 install pytest pyserial
```

---

### Task 1: `lora_queue.py` — spool core (enqueue / list / mark_sent)

**Files:**
- Create: `lora_queue.py`
- Create: `tests/conftest.py`
- Test: `tests/test_lora_queue.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces (used by Tasks 3–4):
  - `lora_queue.DEFAULT_SPOOL_DIR: str` (module attr, `~/lora_queue`; functions must read it at call time so tests can monkeypatch it)
  - `enqueue(metrics: dict, spool_dir: str | None = None) -> str` — writes `pending/<unix_ts>_<capture>.json`, returns the path
  - `list_pending(spool_dir: str | None = None) -> list[str]` — absolute paths, oldest-first
  - `mark_sent(path: str, spool_dir: str | None = None, keep: int = 200) -> str` — moves to `sent/`, prunes oldest beyond `keep`

Design note: the spec names pending files `<capture_dir>.json`. We prefix the unix
timestamp (`<unix_ts>_<capture_dir>.json`) so alphabetical order stays chronological
even when different `--label` prefixes are mixed in one spool.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:

```python
import os
import sys

# Make repo-root modules (lora_queue, lora_sender, pipeline, ...) importable from tests/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`tests/test_lora_queue.py`:

```python
import json
import os

import lora_queue


def _metrics(ts='2026-07-04T10:00:00', capture='BridgeSpan_260704_100000'):
    return {'timestamp': ts, 'capture': capture,
            'dominant_frequency_hz': 2.03,
            'displacement_rms_mm': 0.0008,
            'max_deflection_mm': 0.002}


def test_enqueue_creates_pending_file(tmp_path):
    spool = str(tmp_path)
    path = lora_queue.enqueue(_metrics(), spool_dir=spool)
    assert os.path.isfile(path)
    assert os.sep + 'pending' + os.sep in path
    with open(path) as fh:
        assert json.load(fh)['capture'] == 'BridgeSpan_260704_100000'


def test_list_pending_oldest_first_across_labels(tmp_path):
    spool = str(tmp_path)
    lora_queue.enqueue(_metrics('2026-07-04T12:00:00', 'Zebra_260704_120000'), spool_dir=spool)
    lora_queue.enqueue(_metrics('2026-07-04T09:00:00', 'Alpha_260704_090000'), spool_dir=spool)
    names = [os.path.basename(p) for p in lora_queue.list_pending(spool)]
    assert 'Alpha' in names[0]
    assert 'Zebra' in names[1]


def test_mark_sent_moves_and_prunes(tmp_path):
    spool = str(tmp_path)
    for i in range(5):
        lora_queue.enqueue(_metrics(f'2026-07-04T10:0{i}:00', f'Cap_{i}'), spool_dir=spool)
    for p in lora_queue.list_pending(spool):
        lora_queue.mark_sent(p, spool_dir=spool, keep=3)
    assert lora_queue.list_pending(spool) == []
    sent = sorted(os.listdir(os.path.join(spool, 'sent')))
    assert len(sent) == 3
    assert 'Cap_2' in sent[0]


def test_enqueue_without_timestamp_still_works(tmp_path):
    spool = str(tmp_path)
    path = lora_queue.enqueue({'capture': 'NoTs_1'}, spool_dir=spool)
    assert os.path.isfile(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mac/Documents/Projects/mmwave-cli && python3 -m pytest tests/test_lora_queue.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'lora_queue'`

- [ ] **Step 3: Write the implementation**

`lora_queue.py`:

```python
#!/usr/bin/env python3
"""
LoRa store-and-forward queue (file spool).

Layout:  <spool>/pending/  — waiting for delivery, filename <unix_ts>_<capture>.json
         <spool>/sent/     — delivered (ACKed) messages, newest SENT_KEEP kept
         <spool>/failed/   — corrupt files moved aside so they never block the queue

Plain JSON files: survives reboot/power loss, inspectable over SSH.
"""
import json
import os
import shutil
import time
from datetime import datetime, timezone

DEFAULT_SPOOL_DIR = os.path.expanduser('~/lora_queue')
SENT_KEEP = 200


def _dirs(spool_dir):
    spool_dir = spool_dir or DEFAULT_SPOOL_DIR
    pending = os.path.join(spool_dir, 'pending')
    sent = os.path.join(spool_dir, 'sent')
    failed = os.path.join(spool_dir, 'failed')
    for d in (pending, sent, failed):
        os.makedirs(d, exist_ok=True)
    return pending, sent, failed


def _ts_unix(metrics):
    ts_raw = metrics.get('timestamp')
    if ts_raw:
        try:
            dt = datetime.fromisoformat(ts_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            pass
    return int(time.time())


def enqueue(metrics, spool_dir=None):
    """Write metrics into pending/. Returns the file path."""
    pending, _, _ = _dirs(spool_dir)
    capture = metrics.get('capture', 'unknown')
    path = os.path.join(pending, f'{_ts_unix(metrics):010d}_{capture}.json')
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(metrics, fh)
    os.replace(tmp, path)  # atomic: no half-written pending files after power loss
    return path


def list_pending(spool_dir=None):
    """Absolute paths of pending messages, oldest-first."""
    pending, _, _ = _dirs(spool_dir)
    return sorted(os.path.join(pending, n)
                  for n in os.listdir(pending) if n.endswith('.json'))


def mark_sent(path, spool_dir=None, keep=SENT_KEEP):
    """Move a delivered message to sent/ and prune sent/ to the newest `keep`."""
    _, sent, _ = _dirs(spool_dir)
    dst = os.path.join(sent, os.path.basename(path))
    shutil.move(path, dst)
    names = sorted(n for n in os.listdir(sent) if n.endswith('.json'))
    for n in names[:-keep]:
        os.remove(os.path.join(sent, n))
    return dst
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_lora_queue.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add lora_queue.py tests/conftest.py tests/test_lora_queue.py
git commit -m "feat(lora): add file-spool queue core (enqueue/list/mark_sent)"
```

---

### Task 2: `lora_sender.py` — session + confirmed uplink

**Files:**
- Modify: `lora_sender.py` (add `open_session`, `send_payload_confirmed`; refactor `send_lora` to use `open_session`)
- Test: `tests/test_lora_sender.py`

**Interfaces:**
- Consumes: existing `_send_at(ser, cmd, timeout, expected)`, `encode_payload(metrics)`, module constants `DEFAULT_PORT/BAUD/APPKEY/DR/ADR`.
- Produces (used by Tasks 3–4):
  - `open_session(port=DEFAULT_PORT, baud=DEFAULT_BAUD, appkey=DEFAULT_APPKEY, dr=DEFAULT_DR, adr=DEFAULT_ADR, ser_factory=None) -> serial.Serial | None` — opens + configures + joins; returns a ready handle or `None` (caller must `close()`)
  - `send_payload_confirmed(ser, hex_payload: str, timeout: float = 30.0) -> bool` — `AT+CMSGHEX`, `True` only on `ACK Received`

- [ ] **Step 1: Write the failing tests**

`tests/test_lora_sender.py`:

```python
import lora_sender


class FakeSerial:
    """Scripted Wio-E5. script: dict {command-prefix: [response lines]}.
    Longest matching prefix wins ('AT+JOIN' beats 'AT')."""

    def __init__(self, script):
        self.script = script
        self.buffer = []
        self.written = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def write(self, data):
        cmd = data.decode().strip()
        self.written.append(cmd)
        key = max((k for k in self.script if cmd.startswith(k)), key=len, default=None)
        self.buffer = [l + '\r\n' for l in self.script.get(key, ['OK'])]

    def readline(self):
        return self.buffer.pop(0).encode()

    def reset_input_buffer(self):
        self.buffer = []

    def flush(self):
        pass

    def close(self):
        self.closed = True


JOIN_OK = {
    'AT+KEY': ['+KEY: APPKEY'],
    'AT+ADR': ['+ADR: ON'],
    'AT+DR': ['+DR: DR5'],
    'AT+JOIN': ['+JOIN: Network joined', '+JOIN: Done'],
    'AT': ['+AT: OK'],
}


def _no_sleep(monkeypatch):
    monkeypatch.setattr(lora_sender.time, 'sleep', lambda s: None)


def test_open_session_joins(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial(JOIN_OK)
    ses = lora_sender.open_session(ser_factory=lambda: fake)
    assert ses is fake
    assert any(w.startswith('AT+JOIN') for w in fake.written)


def test_open_session_join_failed_returns_none(monkeypatch):
    _no_sleep(monkeypatch)
    script = dict(JOIN_OK)
    script['AT+JOIN'] = ['+JOIN: Join failed']
    fake = FakeSerial(script)
    ses = lora_sender.open_session(ser_factory=lambda: fake)
    assert ses is None
    assert fake.closed


def test_send_confirmed_ack(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial({'AT+CMSGHEX': ['+CMSGHEX: Start', '+CMSGHEX: Wait ACK',
                                      '+CMSGHEX: ACK Received', '+CMSGHEX: Done']})
    assert lora_sender.send_payload_confirmed(fake, 'AABB', timeout=0.5) is True


def test_send_confirmed_no_ack_is_failure(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial({'AT+CMSGHEX': ['+CMSGHEX: Start', '+CMSGHEX: Done']})
    assert lora_sender.send_payload_confirmed(fake, 'AABB', timeout=0.5) is False
```

Note: `_send_at`'s read loop calls `time.sleep(0.05)` only when the buffer is
empty; with `timeout=0.5` the no-ACK test finishes in ~0.5 s real time.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_lora_sender.py -v`
Expected: FAIL with `AttributeError: module 'lora_sender' has no attribute 'open_session'`

- [ ] **Step 3: Add `open_session` and `send_payload_confirmed`**

In `lora_sender.py`, insert after `find_latest_metrics()` (before the
"Main send function" section):

```python
# ═════════════════════════════════════════════
# Session + confirmed uplink  (used by lora_queue drain)
# ═════════════════════════════════════════════

def open_session(port: str = DEFAULT_PORT,
                 baud: int = DEFAULT_BAUD,
                 appkey: str = DEFAULT_APPKEY,
                 dr: int = DEFAULT_DR,
                 adr: bool = DEFAULT_ADR,
                 ser_factory=None):
    """
    Open the Wio-E5 serial port, configure (APPKEY/ADR/DR) and join OTAA.
    Returns a ready serial handle for repeated sends, or None on failure.
    Caller is responsible for closing the returned handle.
    `ser_factory` allows tests to inject a fake serial object.
    """
    try:
        ser = ser_factory() if ser_factory else serial.Serial(port, baud, timeout=1)
    except serial.SerialException as exc:
        _log(f'ERROR: Cannot open {port}: {exc}')
        return None

    time.sleep(0.5)
    ser.reset_input_buffer()

    ok = False
    for _retry in range(4):
        ok, _ = _send_at(ser, 'AT', timeout=3, expected='OK')
        if ok:
            break
        _log(f'AT no response — retry {_retry + 1}/4...')
    if not ok:
        _log('ERROR: No response from Wio-E5 — check cable and port')
        ser.close()
        return None

    _send_at(ser, f'AT+KEY=APPKEY,"{appkey}"', timeout=3)
    if adr:
        ok_adr, _ = _send_at(ser, 'AT+ADR=ON', timeout=3, expected='ADR')
        if not ok_adr:
            _log('WARNING: AT+ADR=ON not confirmed — continuing...')
    ok_dr, _ = _send_at(ser, f'AT+DR={dr}', timeout=3, expected='DR')
    if not ok_dr:
        _log(f'WARNING: AT+DR={dr} not confirmed — continuing...')

    ok, _ = _send_at(ser, 'AT+JOIN', timeout=30, expected='joined')
    if not ok:
        _log('WARNING: Join may have failed — attempting force rejoin...')
        ok, _ = _send_at(ser, 'AT+JOIN=FORCE', timeout=30, expected='joined')
        if not ok:
            _log('ERROR: Join failed')
            ser.close()
            return None

    # Let all join response lines finish before the first send
    # (avoids "+JOIN: Done" leaking into the next response buffer)
    time.sleep(2)
    ser.reset_input_buffer()
    return ser


def send_payload_confirmed(ser, hex_payload: str, timeout: float = 30.0) -> bool:
    """
    Confirmed uplink via AT+CMSGHEX. True only when the network ACK arrives.
    Without ACK (gateway down, out of range) the Wio-E5 prints '+CMSGHEX: Done'
    but never 'ACK Received' — that is a delivery failure.
    """
    ok, _ = _send_at(ser, f'AT+CMSGHEX="{hex_payload}"',
                     timeout=timeout, expected='ACK Received')
    if ok:
        _log(f'✓ Confirmed uplink delivered (ACK) — {hex_payload}')
    else:
        _log('✗ No ACK received — delivery failed, message stays queued')
    return ok
```

- [ ] **Step 4: Refactor `send_lora` to use `open_session`**

Replace the body of `send_lora` from the `# ── Open serial port ──` comment
down to (and including) the `finally:` block with:

```python
    # ── Open + join session ───────────────────────────────────────────
    ser = open_session(port=port, baud=baud, appkey=appkey, dr=dr, adr=adr)
    if ser is None:
        return False

    try:
        # ── Send payload (unconfirmed, legacy path) ────────────────────
        _log('Sending payload...')
        ok, resp = _send_at(ser, f'AT+MSGHEX="{hex_payload}"',
                            timeout=15, expected='Done')
        if ok:
            _log(f'✓ Uplink sent successfully — payload: {hex_payload}')
        else:
            _log('WARNING: No "Done" received — packet may not have been sent')
        return ok
    finally:
        ser.close()
        _log(f'Serial port {port} closed')
```

(The AT-wake retry loop, APPKEY, ADR, DR, and JOIN blocks previously inside
`send_lora` are deleted — `open_session` now owns that sequence.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_lora_sender.py tests/test_lora_queue.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add lora_sender.py tests/test_lora_sender.py
git commit -m "feat(lora): confirmed uplink (AT+CMSGHEX) + reusable join session"
```

---

### Task 3: `lora_queue.drain()` — oldest-first delivery

**Files:**
- Modify: `lora_queue.py`
- Test: `tests/test_lora_queue.py` (append)

**Interfaces:**
- Consumes: `lora_sender.encode_payload(metrics) -> str` (imported lazily inside `drain` so `lora_queue` stays importable without pyserial), Task 1 spool functions.
- Produces (used by Task 4):
  - `drain(send_fn, spool_dir=None, max_send=20, spacing_s=10.0, sleep_fn=time.sleep) -> tuple[int, int]` — `(sent_count, remaining_count)`; `send_fn(hex_payload: str) -> bool`; stops at first `False` (link down) or `max_send`; corrupt files go to `failed/`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lora_queue.py`:

```python
def test_drain_oldest_first_and_stops_on_failure(tmp_path):
    spool = str(tmp_path)
    for i in range(4):
        lora_queue.enqueue(_metrics(f'2026-07-04T10:0{i}:00', f'Cap_{i}'), spool_dir=spool)

    results = iter([True, True, False])   # 3rd send fails → drain must stop
    sent_payloads = []

    def send_fn(hex_payload):
        sent_payloads.append(hex_payload)
        return next(results)

    sent, remaining = lora_queue.drain(send_fn, spool_dir=spool, sleep_fn=lambda s: None)
    assert sent == 2
    assert remaining == 2                  # Cap_2 (failed) and Cap_3 stay pending
    assert len(sent_payloads) == 3
    pending_names = [p.split('_')[-1] for p in lora_queue.list_pending(spool)]
    assert pending_names == ['2.json', '3.json']


def test_drain_respects_max_send_and_spacing(tmp_path):
    spool = str(tmp_path)
    for i in range(5):
        lora_queue.enqueue(_metrics(f'2026-07-04T10:0{i}:00', f'Cap_{i}'), spool_dir=spool)
    sleeps = []
    sent, remaining = lora_queue.drain(lambda h: True, spool_dir=spool,
                                       max_send=3, spacing_s=10.0,
                                       sleep_fn=sleeps.append)
    assert (sent, remaining) == (3, 2)
    assert sleeps == [10.0, 10.0]          # spacing between sends, not before the first


def test_drain_moves_corrupt_file_to_failed(tmp_path):
    spool = str(tmp_path)
    lora_queue.enqueue(_metrics('2026-07-04T10:00:00', 'Good_1'), spool_dir=spool)
    import os
    bad = os.path.join(spool, 'pending', '0000000001_bad.json')
    with open(bad, 'w') as fh:
        fh.write('{not json')
    sent, remaining = lora_queue.drain(lambda h: True, spool_dir=spool, sleep_fn=lambda s: None)
    assert (sent, remaining) == (1, 0)
    assert os.listdir(os.path.join(spool, 'failed')) == ['0000000001_bad.json']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_lora_queue.py -v`
Expected: 3 new tests FAIL with `AttributeError: module 'lora_queue' has no attribute 'drain'`

- [ ] **Step 3: Implement `drain` (append to `lora_queue.py`)**

```python
def drain(send_fn, spool_dir=None, max_send=20, spacing_s=10.0, sleep_fn=time.sleep):
    """
    Send pending messages oldest-first via send_fn(hex_payload) -> bool.
    Stops at the first failure (link considered down) or after max_send.
    Corrupt files are moved to failed/ so they never block the queue.
    Returns (sent_count, remaining_count).
    """
    from lora_sender import encode_payload  # lazy: keeps lora_queue importable without pyserial
    _, _, failed_dir = _dirs(spool_dir)
    sent_count = 0
    for path in list_pending(spool_dir):
        if sent_count >= max_send:
            print(f'[QUEUE] max_send={max_send} reached — remaining backlog drains next cycle')
            break
        try:
            with open(path) as fh:
                metrics = json.load(fh)
            hex_payload = encode_payload(metrics)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            print(f'[QUEUE] Corrupt spool file {os.path.basename(path)} ({exc}) — moving to failed/')
            shutil.move(path, os.path.join(failed_dir, os.path.basename(path)))
            continue
        if sent_count > 0:
            sleep_fn(spacing_s)
        if not send_fn(hex_payload):
            break
        mark_sent(path, spool_dir)
        sent_count += 1
    return sent_count, len(list_pending(spool_dir))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_lora_queue.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add lora_queue.py tests/test_lora_queue.py
git commit -m "feat(lora): oldest-first queue drain with failure stop + corrupt quarantine"
```

---

### Task 4: Pipeline Step 5 = enqueue + drain; queue CLI

**Files:**
- Modify: `pipeline.py` (replace `run_lora_send` with `run_lora_step`; call sites in main loop)
- Modify: `lora_queue.py` (add `__main__` CLI)
- Test: `tests/test_pipeline_lora_step.py`

**Interfaces:**
- Consumes: `lora_queue.enqueue/list_pending/drain`, `lora_sender.open_session/send_payload_confirmed`.
- Produces: `pipeline.run_lora_step(capture_dir: str, port: str, appkey: str, skip_send: bool = False) -> bool` — enqueue always happens; send only when `skip_send=False`. CLI: `python3 lora_queue.py --status` and `python3 lora_queue.py --drain [--port P] [--appkey K]`.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_lora_step.py`:

```python
import json

import lora_queue
import pipeline


def _write_metrics(tmp_path, capture):
    mdir = tmp_path / 'python-result' / capture
    mdir.mkdir(parents=True)
    (mdir / 'ps_metrics.json').write_text(json.dumps({
        'capture': capture, 'timestamp': '2026-07-04T10:00:00',
        'dominant_frequency_hz': 2.0, 'displacement_rms_mm': 0.001,
        'max_deflection_mm': 0.002}))


def test_skip_lora_still_enqueues(tmp_path, monkeypatch):
    monkeypatch.setattr(lora_queue, 'DEFAULT_SPOOL_DIR', str(tmp_path / 'spool'))
    monkeypatch.setattr(pipeline, 'EDGE_DIR', str(tmp_path))
    cap = 'T_260704_100000'
    _write_metrics(tmp_path, cap)
    ok = pipeline.run_lora_step(cap, port='/dev/null', appkey='X', skip_send=True)
    assert ok is True
    assert len(lora_queue.list_pending()) == 1


def test_link_down_keeps_backlog(tmp_path, monkeypatch):
    import lora_sender
    monkeypatch.setattr(lora_queue, 'DEFAULT_SPOOL_DIR', str(tmp_path / 'spool'))
    monkeypatch.setattr(pipeline, 'EDGE_DIR', str(tmp_path))
    monkeypatch.setattr(lora_sender, 'open_session', lambda **kw: None)
    cap = 'T_260704_100001'
    _write_metrics(tmp_path, cap)
    ok = pipeline.run_lora_step(cap, port='/dev/null', appkey='X')
    assert ok is False
    assert len(lora_queue.list_pending()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_pipeline_lora_step.py -v`
Expected: FAIL with `AttributeError: module 'pipeline' has no attribute 'run_lora_step'`

- [ ] **Step 3: Replace Step 5 in `pipeline.py`**

Add `import json` to the imports at the top of `pipeline.py`.

Replace the whole `run_lora_send` function (the `# Step 5 — LoRa uplink (Wio-E5)`
section) with:

```python
# ─────────────────────────────────────────────
# Step 5 — LoRa uplink via store-and-forward queue (Wio-E5)
# ─────────────────────────────────────────────

def run_lora_step(capture_dir: str, port: str, appkey: str,
                  skip_send: bool = False) -> bool:
    """Enqueue this cycle's metrics, then drain the spool (oldest-first,
    confirmed uplinks). Enqueue always happens — even with --skip-lora —
    so no data is ever lost. Returns True when the spool is empty afterwards."""
    import lora_queue
    import lora_sender

    _banner(f'STEP 5 — LoRa Uplink  ({capture_dir})')

    metrics_path = os.path.join(EDGE_DIR, 'python-result', capture_dir, 'ps_metrics.json')
    if os.path.isfile(metrics_path):
        with open(metrics_path) as fh:
            metrics = json.load(fh)
        spooled = lora_queue.enqueue(metrics)
        _step(f'Queued → {os.path.basename(spooled)}')
    else:
        print(f'[PIPELINE] WARNING: ps_metrics.json not found: {metrics_path} — nothing to queue')

    pending = lora_queue.list_pending()
    if skip_send:
        _step(f'LoRa send skipped (--skip-lora) — {len(pending)} message(s) queued')
        return True
    if not pending:
        _step('LoRa queue empty — nothing to send')
        return True

    ses = lora_sender.open_session(port=port, appkey=appkey)
    if ses is None:
        _step(f'LoRa link unavailable — {len(pending)} message(s) remain queued')
        return False
    try:
        sent, remaining = lora_queue.drain(
            lambda hex_payload: lora_sender.send_payload_confirmed(ses, hex_payload))
    finally:
        ses.close()
    _step(f'LoRa drain: {sent} sent, {remaining} still pending')
    return remaining == 0
```

In `main()`, replace the Step 5 block:

```python
        # ── 5. LoRa uplink (store-and-forward) ──────────────────────
        t5 = _step_start('Step 5 — LoRa Uplink')
        run_lora_step(capture_dir, args.lora_port, args.lora_appkey,
                      skip_send=args.skip_lora)
        _step_done('Step 5 — LoRa Uplink', t5)
```

(the old `if not args.skip_lora: ... else: skipped` branch disappears — the
function itself handles `--skip-lora`). Update the `--skip-lora` help string to:
`'Skip LoRa sending (metrics are still queued in ~/lora_queue for later drain)'`.

- [ ] **Step 4: Add CLI to `lora_queue.py` (append at end)**

```python
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='LoRa store-and-forward queue')
    parser.add_argument('--status', action='store_true', help='Show queue counts')
    parser.add_argument('--drain', action='store_true', help='Send all pending now')
    parser.add_argument('--port', default='/dev/ttyUSB0')
    parser.add_argument('--appkey', default=None)
    args = parser.parse_args()

    if args.drain:
        import lora_sender
        ses = lora_sender.open_session(
            port=args.port, appkey=args.appkey or lora_sender.DEFAULT_APPKEY)
        if ses is None:
            raise SystemExit('LoRa link unavailable')
        try:
            sent, remaining = drain(
                lambda h: lora_sender.send_payload_confirmed(ses, h))
        finally:
            ses.close()
        print(f'drained: {sent} sent, {remaining} pending')
    else:
        print(f'pending: {len(list_pending())}')
```

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add pipeline.py lora_queue.py tests/test_pipeline_lora_step.py
git commit -m "feat(pipeline): Step 5 = enqueue + confirmed drain; lora_queue CLI"
```

---

### Task 5: `mmwcas.pyx` — no fatal exit; `mimo.py` handles init failure

**Files:**
- Modify: `mmwcas.pyx:440-474` (`check`), `:477-515` (`initMaster`), `:517-562` (`initSlaves`), `:564-643` (`configure`), `:716-728` (`mmw_init`)
- Modify: `mimo.py:93-102` (init error handling; also pass `args.tda_ip`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `mmwcas.mmw_init(ip_addr: str, port: int = 5001) -> int` now returns non-zero instead of killing the process; `configure` short-circuits after the first failed stage. `mimo.py` exits with code 2 (after powerOff teardown) when init fails.

⚠️ This task builds/verifies **on the Raspberry Pi only**. Pure-Python tests still run on the Mac (`python3 -m pytest tests/ -v` must stay green — it does not import mmwcas).

- [ ] **Step 1: Neuter the fatal exit in `check()`**

In `mmwcas.pyx`, replace:

```cython
        # 如果 is_required 为非零，则退出程序
        if is_required != 0:
            exit(status)
```

with:

```cython
        # Never exit() from C level: return control to Python so the caller
        # (pipeline recovery ladder) can decide. is_required kept for signature
        # compatibility; failure is signalled by the returned status upstream.
```

- [ ] **Step 2: Short-circuit `initMaster` after each failed stage**

Since `check()` no longer aborts, each stage must stop the sequence itself
(running later stages against a dead device just burns 1–3 s timeouts each).
Insert `if status != 0: return status` after **every** `check(...)` call in
`initMaster`. Full new body:

```cython
cdef int32_t initMaster(rlChanCfg_t channelCfg,rlAdcOutCfg_t adcOutCfg):
    cdef unsigned int masterId = 0
    cdef unsigned int masterMap = 1U << masterId
    cdef int status = 0
    channelCfg.cascading = 1
    status += MMWL_DevicePowerUp(masterMap, 1000, 1000)
    check(status,
        b"[MASTER] Power up successful!",
        b"[MASTER] Error: Failed to power up device!", masterMap, TRUE)
    if status != 0:
        return status

    status += MMWL_firmwareDownload(masterMap)
    check(status,
        b"[MASTER] Firmware successfully uploaded!",
        b"[MASTER] Error: Firmware upload failed!", masterMap, TRUE)
    if status != 0:
        return status

    status += MMWL_setDeviceCrcType(masterMap)
    check(status,
        b"[MASTER] CRC type has been set!",
        b"[MASTER] Error: Unable to set CRC type!", masterMap, TRUE)
    if status != 0:
        return status

    status += MMWL_rfEnable(masterMap)
    check(status,
        b"[MASTER] RF successfully enabled!",
        b"[MASTER] Error: Failed to enable master RF", masterMap, TRUE)
    if status != 0:
        return status

    status += MMWL_channelConfig(masterMap, channelCfg.cascading, channelCfg)
    check(status,
        b"[MASTER] Channels successfully configured!",
        b"[MASTER] Error: Channels configuration failed!", masterMap, TRUE)
    if status != 0:
        return status

    status += MMWL_adcOutConfig(masterMap, adcOutCfg)
    check(status,
        b"[MASTER] ADC output format successfully configured!",
        b"[MASTER] Error: ADC output format configuration failed!", masterMap, TRUE)
    if status != 0:
        return status

    check(status,
        b"[MASTER] Init completed with sucess",
        b"[MASTER] Init completed with error", masterMap, TRUE)
    return status
```

- [ ] **Step 3: Same pattern in `initSlaves`**

Full new body (note: the power-up loop breaks out on failure):

```cython
cdef int32_t initSlaves(rlChanCfg_t channelCfg, rlAdcOutCfg_t adcOutCfg):
    cdef int status = 0
    cdef uint8_t slavesMap = (1 << 1) | (1 << 2) | (1 << 3)
    cdef unsigned int slaveMap

    # slave chip
    channelCfg.cascading = 2

    for slaveId in range(1,4):
        slaveMap = 1 << slaveId

        status += MMWL_DevicePowerUp(slaveMap, 1000, 1000)
        check(status,
            b"[SLAVE] Power up successful!",
            b"[SLAVE] Error: Failed to power up device!", slaveMap, TRUE)
        if status != 0:
            return status

    #Config of all slaves together
    status += MMWL_firmwareDownload(slavesMap)
    check(status,
        b"[SLAVE] Firmware successfully uploaded!",
        b"[SLAVE] Error: Firmware upload failed!", slavesMap, TRUE)
    if status != 0:
        return status

    status += MMWL_setDeviceCrcType(slavesMap)
    check(status,
        b"[SLAVE] CRC type has been set!",
        b"[SLAVE] Error: Unable to set CRC type!", slavesMap, TRUE)
    if status != 0:
        return status

    status += MMWL_rfEnable(slavesMap)
    check(status,
        b"[SLAVE] RF successfully enabled!",
        b"[SLAVE] Error: Failed to enable master RF", slavesMap, TRUE)
    if status != 0:
        return status

    status += MMWL_channelConfig(slavesMap, channelCfg.cascading,channelCfg)
    check(status,
        b"[SLAVE] Channels successfully configured!",
        b"[SLAVE] Error: Channels configuration failed!", slavesMap, TRUE)
    if status != 0:
        return status

    status += MMWL_adcOutConfig(slavesMap, adcOutCfg)
    check(status,
        b"[SLAVE] ADC output format successfully configured!",
        b"[SLAVE] Error: ADC output format configuration failed!", slavesMap, TRUE)
    if status != 0:
        return status

    check(status,
        b"[SLAVE] Init completed with sucess",
        b"[SLAVE] Init completed with error", slavesMap, TRUE)
    return status
```

- [ ] **Step 4: Same pattern in `configure`**

Insert `if status != 0:` + `    return status` immediately after **each** of
these existing lines in `configure` (and after the two `initMaster`/`initSlaves`
calls at the top):

```cython
cdef uint32_t configure (devConfig_t config):
    cdef int status = 0
    cdef int devId = 0
    status += initMaster(config.channelCfg, config.adcOutCfg)
    if status != 0:
        return status
    status += initSlaves(config.channelCfg, config.adcOutCfg)
    if status != 0:
        return status
```

then after each of the seven remaining `check(...)` calls in the function
(`RF device configured`, `LDO Bypass`, `Data format`, `Low Power Mode`,
`RF init`, `Datapath`, `Profile`, `Chirp`, master `Frame`, slave `Frame`) add:

```cython
    if status != 0:
        return status
```

(the final slave-frame `check` is followed by the existing `return status`, so
no extra insert needed there).

- [ ] **Step 5: `mmw_init` returns the configure status**

Replace `mmw_init`:

```cython
cpdef int mmw_init(
    str ip_addr="192.168.33.180",
    int port = 5001,
    ):
    cdef int status = 0
    cdef bytes ip_addr_bytes = ip_addr.encode('utf-8')
    status = MMWL_TDAInit(ip_addr_bytes,port,config.deviceMap)
    check(status,
        b"[MMWCAS-DSP] TDA Connected!",
        b"[MMWCAS-DSP] Couldn't connect to TDA board!", 32, TRUE)
    if status != 0:
        return status

    status = <int>configure(config)
    return status
```

- [ ] **Step 6: `mimo.py` handles init failure (and finally passes `--tda-ip`)**

Replace `mimo.py:93-102`:

```python
    # Configure radar
    status = mmwcas.mmw_set_config(config_dict)
    if status != 0:
        print(f"Configuration error: {status}")
        sys.exit(2)

    # Initialize radar (heavy phase). With the non-exiting mmwcas, a failure
    # here returns a status code instead of killing the interpreter.
    status = mmwcas.mmw_init(args.tda_ip)
    if status != 0:
        print(f"mmw_init failed (status: {status}) — powering off and exiting")
        if hasattr(mmwcas, "mmw_power_off"):
            try:
                mmwcas.mmw_power_off()
            except Exception as e:
                print(f"[MMWCAS] WARNING: power-off after failed init failed: {e}")
        sys.exit(2)
    time.sleep(2)
```

(Note `mmw_init(args.tda_ip)` — the existing code silently ignored `--tda-ip`.)

- [ ] **Step 7: Mac-side sanity + commit**

Run: `python3 -m pytest tests/ -v` (must stay green — nothing imports mmwcas)
Run: `python3 -m py_compile mimo.py pipeline.py`
Expected: no output (compile OK)

```bash
git add mmwcas.pyx mimo.py
git commit -m "fix(mmwcas): never exit() from C level — init errors return to Python"
```

- [ ] **Step 8: Build + verify on the Raspberry Pi**

```bash
ssh imrsl@imrslpi5-02   # password: imrsl2022
cd ~/mmwave-cli && git fetch && git checkout feat/reliability && git pull
make build
python3 -c "import mmwcas; print('mmwcas OK')"
# Negative test — wrong IP must produce a clean Python-level exit (code 2),
# NOT a silent C-level exit:
python3 mimo.py --tda-ip 192.168.33.99 -t 1; echo "exit=$?"
# Expected: "mmw_init failed (status: ...)" then "exit=2"
# Positive test — real capture must still work end-to-end:
python3 mimo.py -t 5 --directory RelTest; echo "exit=$?"
# Expected: capture completes, files verified, exit=0
```

---

### Task 6: `tda_recovery.py` — pre-flight + trace cleanup

**Files:**
- Create: `tda_recovery.py`
- Test: `tests/test_tda_recovery.py`

**Interfaces:**
- Consumes: nothing from other tasks (stdlib only; **must not import mmwcas**).
- Produces (used by Tasks 7–8):
  - `ssh_run(ip: str, cmd: str, timeout: float = 30) -> tuple[int, str]` — `(returncode, stdout)`; `(255, '')` on timeout/error
  - `preflight(ip: str, run=None, min_free_mb: int = 200, log_path: str | None = None) -> bool`
  - `clean_tda_traces(ip: str, run=None, keep: int = 20, log_path=None) -> bool`
  - `log_event(action: str, detail: str = '', streak: int | None = None, path: str | None = None) -> None` — appends to `recovery_log.jsonl` next to this file
  - `RECOVERY_LOG: str`, `TRACE_DIR = '/opt/vision_sdk'`

- [ ] **Step 1: Write the failing tests**

`tests/test_tda_recovery.py`:

```python
import json

import tda_recovery


DF_OK = '/dev/root 1500000 1200000 300000 80% /'      # 300000 KB ≈ 293 MB free
DF_LOW = '/dev/root 1500000 1450000 50000 97% /'      # 50000 KB ≈ 49 MB free


def test_preflight_ok(tmp_path):
    log = str(tmp_path / 'rec.jsonl')
    calls = []

    def run(ip, cmd, timeout=30):
        calls.append(cmd)
        return 0, f'APPS_OK\n{DF_OK}\n'

    assert tda_recovery.preflight('1.2.3.4', run=run, log_path=log) is True
    assert len(calls) == 1


def test_preflight_unreachable(tmp_path):
    log = str(tmp_path / 'rec.jsonl')
    assert tda_recovery.preflight('1.2.3.4', run=lambda *a, **k: (255, ''),
                                  log_path=log) is False
    events = [json.loads(l) for l in open(log)]
    assert events[0]['action'] == 'preflight_unreachable'


def test_preflight_apps_down(tmp_path):
    log = str(tmp_path / 'rec.jsonl')
    run = lambda ip, cmd, timeout=30: (0, f'APPS_DOWN\n{DF_OK}\n')
    assert tda_recovery.preflight('1.2.3.4', run=run, log_path=log) is False


def test_preflight_low_disk_triggers_cleanup(tmp_path):
    log = str(tmp_path / 'rec.jsonl')
    cmds = []

    def run(ip, cmd, timeout=30):
        cmds.append(cmd)
        return 0, (f'APPS_OK\n{DF_LOW}\n' if len(cmds) == 1 else f'{DF_OK}\n')

    assert tda_recovery.preflight('1.2.3.4', run=run, log_path=log) is True
    assert len(cmds) == 2
    assert 'Trace_TDA_*.txt' in cmds[1]


def test_log_event_appends_jsonl(tmp_path):
    log = str(tmp_path / 'rec.jsonl')
    tda_recovery.log_event('light_retry', 'backoff=5', streak=1, path=log)
    tda_recovery.log_event('recovered', path=log)
    events = [json.loads(l) for l in open(log)]
    assert [e['action'] for e in events] == ['light_retry', 'recovered']
    assert events[0]['streak'] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tda_recovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tda_recovery'`

- [ ] **Step 3: Implement `tda_recovery.py` (pre-flight half)**

```python
#!/usr/bin/env python3
"""
TDA pre-flight checks + escalating recovery ladder.

Hardware-agnostic: never imports mmwcas. All side effects (SSH, shell,
sleeping) are injectable for tests. See TIDEP-01012.md §5, §10, §11 for the
failure catalog this addresses, and the design spec
docs/superpowers/specs/2026-07-04-reliability-tda-lora-design.md.
"""
import json
import os
import subprocess
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RECOVERY_LOG = os.path.join(SCRIPT_DIR, 'recovery_log.jsonl')

TRACE_DIR = '/opt/vision_sdk'       # where apps.out writes Trace_TDA_*.txt (TIDEP-01012.md §11)
SSH_OPTS = [
    '-oHostKeyAlgorithms=+ssh-rsa',
    '-oPubkeyAcceptedAlgorithms=+ssh-rsa',
    '-oStrictHostKeyChecking=no',
    '-oConnectTimeout=10',
]

# One SSH round-trip answers both pre-flight questions:
#   line 1: APPS_OK / APPS_DOWN   (is the capture service alive?)
#   line 2: df -k output           (is the rootfs about to fill up?)
PREFLIGHT_CMD = ("pgrep -f apps.out >/dev/null && echo APPS_OK || echo APPS_DOWN; "
                 "df -k / | tail -1")


def log_event(action, detail='', streak=None, path=None):
    """Append one structured recovery event to recovery_log.jsonl."""
    rec = {'ts': datetime.now().isoformat(timespec='seconds'),
           'action': action, 'detail': detail}
    if streak is not None:
        rec['streak'] = streak
    with open(path or RECOVERY_LOG, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')
    print(f'[RECOVERY] {action}  {detail}', flush=True)


def ssh_run(ip, cmd, timeout=30):
    """Run a command on the TDA as root. Returns (returncode, stdout)."""
    try:
        r = subprocess.run(['ssh', *SSH_OPTS, f'root@{ip}', cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 255, ''


def _parse_df_free_mb(out):
    """Free MB from a `df -k` output line; None if unparseable."""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].isdigit() and parts[3].isdigit():
            return int(parts[3]) // 1024
    return None


def clean_tda_traces(ip, run=None, keep=20, log_path=None):
    """Delete oldest Trace_TDA_*.txt on the TDA rootfs, keeping the newest `keep`.
    Prevents the rootfs-full total failure of TIDEP-01012.md §11."""
    run = run or ssh_run
    cmd = (f"cd {TRACE_DIR} && ls -1t Trace_TDA_*.txt 2>/dev/null "
           f"| tail -n +{keep + 1} | xargs -r rm -f; df -k / | tail -1")
    rc, out = run(ip, cmd, timeout=60)
    free_mb = _parse_df_free_mb(out)
    log_event('tda_trace_cleanup',
              f'rc={rc} free_after={free_mb}MB', path=log_path)
    return rc == 0


def preflight(ip, run=None, min_free_mb=200, log_path=None):
    """True when the TDA is ready for a capture: SSH reachable, apps.out
    running, rootfs not full (auto-cleans traces when below min_free_mb)."""
    run = run or ssh_run
    rc, out = run(ip, PREFLIGHT_CMD)
    if rc != 0:
        log_event('preflight_unreachable', f'ssh rc={rc}', path=log_path)
        return False
    free_mb = _parse_df_free_mb(out)
    if free_mb is not None and free_mb < min_free_mb:
        log_event('preflight_low_disk', f'free={free_mb}MB < {min_free_mb}MB',
                  path=log_path)
        clean_tda_traces(ip, run=run, log_path=log_path)
    if 'APPS_OK' not in out:
        log_event('preflight_apps_down', 'apps.out not running', path=log_path)
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tda_recovery.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add tda_recovery.py tests/test_tda_recovery.py
git commit -m "feat(tda): pre-flight check (apps.out + rootfs) with trace auto-cleanup"
```

---

### Task 7: `tda_recovery.RecoveryPolicy` — the escalating ladder

**Files:**
- Modify: `tda_recovery.py` (append)
- Test: `tests/test_tda_recovery.py` (append)

**Interfaces:**
- Consumes: Task 6 `ssh_run`, `log_event`.
- Produces (used by Tasks 8–9):
  - `RecoveryPolicy(tda_ip, reinit_fn=None, power_cycle_cmd=None, run=None, shell_fn=None, sleep_fn=time.sleep, log_path=None)`
  - `.on_failure() -> str` — performs the next ladder action, returns its name (`light_retry | software_reinit | tda_reboot | power_cycle | ladder_exhausted`)
  - `.on_success() -> None` — resets the failure streak
  - `.streak: int`

- [ ] **Step 1: Write the failing tests (append to `tests/test_tda_recovery.py`)**

```python
def _policy(tmp_path, **kw):
    sleeps = []
    pol = tda_recovery.RecoveryPolicy(
        '1.2.3.4',
        run=kw.pop('run', lambda ip, cmd, timeout=30: (0, 'UP\n')),
        shell_fn=kw.pop('shell_fn', lambda cmd: 0),
        sleep_fn=sleeps.append,
        log_path=str(tmp_path / 'rec.jsonl'),
        **kw)
    return pol, sleeps


def test_ladder_default_mode_sequence(tmp_path):
    pol, sleeps = _policy(tmp_path)          # no reinit_fn, no power_cycle_cmd
    actions = [pol.on_failure() for _ in range(5)]
    assert actions == ['light_retry', 'light_retry', 'light_retry',
                       'tda_reboot', 'ladder_exhausted']
    assert sleeps[:3] == [5, 15, 45]
    assert 600 in sleeps                      # exhausted → long sleep
    assert pol.streak == 0                    # ladder restarted


def test_ladder_persistent_mode_includes_reinit(tmp_path):
    reinits = []
    pol, _ = _policy(tmp_path, reinit_fn=lambda: reinits.append(1))
    actions = [pol.on_failure() for _ in range(6)]
    assert actions == ['light_retry', 'light_retry', 'light_retry',
                       'software_reinit', 'software_reinit', 'tda_reboot']
    assert len(reinits) == 2


def test_ladder_power_cycle_when_configured(tmp_path):
    shell_calls = []
    pol, _ = _policy(tmp_path, power_cycle_cmd='gpio toggle 4',
                     shell_fn=lambda cmd: shell_calls.append(cmd) or 0)
    for _ in range(4):
        pol.on_failure()
    assert pol.on_failure() == 'power_cycle'
    assert shell_calls == ['gpio toggle 4']


def test_success_resets_streak(tmp_path):
    pol, _ = _policy(tmp_path)
    pol.on_failure()
    pol.on_failure()
    pol.on_success()
    assert pol.streak == 0
    assert pol.on_failure() == 'light_retry'


def test_reboot_waits_for_board(tmp_path):
    responses = iter([(0, ''),        # reboot command itself
                      (255, ''), (255, ''), (0, 'UP\n')])  # poll: down, down, up
    pol, sleeps = _policy(tmp_path, run=lambda ip, cmd, timeout=30: next(responses))
    for _ in range(3):
        pol.on_failure()              # burn through light retries
    assert pol.on_failure() == 'tda_reboot'
    # 3 light backoffs + 2×10s down-polls + 20s post-boot grace
    assert sleeps == [5, 15, 45, 10, 10, 20]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tda_recovery.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'RecoveryPolicy'`

- [ ] **Step 3: Implement `RecoveryPolicy` (append to `tda_recovery.py`)**

```python
LIGHT_BACKOFFS_S = (5, 15, 45)
REINIT_ATTEMPTS = 2
REBOOT_WAIT_S = 180
BOOT_POLL_S = 10
POST_BOOT_GRACE_S = 20
LADDER_EXHAUSTED_SLEEP_S = 600


class RecoveryPolicy:
    """Escalating recovery ladder (design spec Part 1b).

    Call on_failure() after every failed capture/pre-flight and on_success()
    after every good capture. Each on_failure() performs ONE ladder action
    (including its waiting) and returns; the caller then simply retries the
    cycle. The ladder never raises — the pipeline must never crash.
    """

    def __init__(self, tda_ip, reinit_fn=None, power_cycle_cmd=None,
                 run=None, shell_fn=None, sleep_fn=time.sleep, log_path=None):
        self.tda_ip = tda_ip
        self.reinit_fn = reinit_fn                  # persistent mode only
        self.power_cycle_cmd = power_cycle_cmd      # e.g. relay toggle command
        self.run = run or ssh_run
        # shell=True is intentional and safe here: power_cycle_cmd is written by
        # the operator on their own CLI (--power-cycle-cmd), never interpolated
        # with untrusted data, and legitimately needs shell features
        # (e.g. "plug-off && sleep 5 && plug-on").
        self.shell = shell_fn or (lambda cmd: subprocess.run(cmd, shell=True).returncode)
        self.sleep = sleep_fn
        self.log_path = log_path
        self.streak = 0
        self.schedule = self._build_schedule()

    def _build_schedule(self):
        sched = [('light_retry', b) for b in LIGHT_BACKOFFS_S]
        if self.reinit_fn is not None:
            sched += [('software_reinit', 5)] * REINIT_ATTEMPTS
        sched.append(('tda_reboot', None))
        if self.power_cycle_cmd:
            sched.append(('power_cycle', None))
        return sched

    def on_success(self):
        if self.streak:
            log_event('recovered', f'after {self.streak} failure(s)',
                      path=self.log_path)
        self.streak = 0

    def on_failure(self):
        if self.streak >= len(self.schedule):
            log_event('ladder_exhausted',
                      f'sleeping {LADDER_EXHAUSTED_SLEEP_S}s, then restarting ladder',
                      streak=self.streak, path=self.log_path)
            self.sleep(LADDER_EXHAUSTED_SLEEP_S)
            self.streak = 0
            return 'ladder_exhausted'

        action, backoff = self.schedule[self.streak]
        self.streak += 1
        log_event(action, f'backoff={backoff}', streak=self.streak,
                  path=self.log_path)

        if action == 'light_retry':
            self.sleep(backoff)
        elif action == 'software_reinit':
            self.sleep(backoff)
            try:
                self.reinit_fn()
            except Exception as exc:
                log_event('software_reinit_error', str(exc), path=self.log_path)
        elif action == 'tda_reboot':
            try:
                self.run(self.tda_ip, 'reboot')
            except Exception as exc:
                log_event('tda_reboot_error', str(exc), path=self.log_path)
            self._wait_board_up()
        elif action == 'power_cycle':
            try:
                self.shell(self.power_cycle_cmd)
            except Exception as exc:
                log_event('power_cycle_error', str(exc), path=self.log_path)
            self._wait_board_up()
        return action

    def _wait_board_up(self):
        """Poll the TDA over SSH until it answers or REBOOT_WAIT_S elapses,
        then give apps.out a grace period to start listening."""
        for _ in range(REBOOT_WAIT_S // BOOT_POLL_S):
            rc, _out = self.run(self.tda_ip, 'echo UP', timeout=BOOT_POLL_S)
            if rc == 0:
                break
            self.sleep(BOOT_POLL_S)
        self.sleep(POST_BOOT_GRACE_S)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tda_recovery.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add tda_recovery.py tests/test_tda_recovery.py
git commit -m "feat(tda): escalating RecoveryPolicy ladder (retry/reinit/reboot/power-cycle)"
```

---

### Task 8: Wire pre-flight + ladder into `pipeline.py` (default mode)

**Files:**
- Modify: `pipeline.py` (main loop `pipeline.py:497-537`; argparse; cycle summary)

**Interfaces:**
- Consumes: `tda_recovery.preflight`, `tda_recovery.RecoveryPolicy`.
- Produces: new args `--power-cycle-cmd` (str, default None) and `--min-tda-free-mb` (int, default 200). Cycle summary line includes `ok/failed` counters.

- [ ] **Step 1: Add import and arguments**

Add `import tda_recovery` to the imports of `pipeline.py`. Add to argparse:

```python
    parser.add_argument('--power-cycle-cmd', type=str, default=None,
                        help='Shell command that hard power-cycles the TDA (relay/smart '
                             'plug). Used as the last recovery-ladder level. Unset = level '
                             'disabled (no relay installed yet).')
    parser.add_argument('--min-tda-free-mb', type=int, default=200,
                        help='Pre-flight: auto-clean Trace_TDA_*.txt on the TDA when its '
                             'rootfs free space drops below this many MB.')
```

- [ ] **Step 2: Create the policy + counters before the loop**

Insert right before `cycle = 0` in `main()`:

```python
    policy = tda_recovery.RecoveryPolicy(args.tda_ip,
                                         power_cycle_cmd=args.power_cycle_cmd)
    stats = {'ok': 0, 'failed': 0}
```

- [ ] **Step 3: Pre-flight at the top of every cycle**

Insert right after the `# CYCLE ...` banner print:

```python
        # ── 0. Pre-flight (TDA reachable, apps.out alive, rootfs not full) ──
        if not tda_recovery.preflight(args.tda_ip, min_free_mb=args.min_tda_free_mb):
            stats['failed'] += 1
            _step(f'Pre-flight failed — recovery: {policy.on_failure()}')
            continue
```

- [ ] **Step 4: Route capture failure through the ladder**

Replace:

```python
        capture_dir = run_capture(args.duration, args.tda_ip, args.label)
        if capture_dir is None:
            print('[PIPELINE] Capture failed — retrying in 10s...')
            time.sleep(10)
            continue
        _step_done('Step 1 — Capture', t1)
```

with:

```python
        capture_dir = run_capture(args.duration, args.tda_ip, args.label)
        if capture_dir is None:
            stats['failed'] += 1
            _step(f'Capture failed — recovery: {policy.on_failure()}')
            continue
        policy.on_success()
        stats['ok'] += 1
        _step_done('Step 1 — Capture', t1)
```

- [ ] **Step 5: Extend the cycle summary**

In the end-of-cycle summary block, after the `Disk free` line add:

```python
        total = stats['ok'] + stats['failed']
        print(f'  Capture success  : {stats["ok"]}/{total} cycles '
              f'({100.0 * stats["ok"] / max(1, total):.0f}%)')
```

- [ ] **Step 6: Verify on the Mac (no hardware needed)**

Run: `python3 -m pytest tests/ -v` — all pass.
Run (unreachable IP → pre-flight fails → ladder engages; Ctrl+C after ~30 s):

```bash
python3 pipeline.py --tda-ip 192.0.2.1 --skip-transfer --skip-ps --skip-lora --duration 1
```

Expected output: `[RECOVERY] preflight_unreachable ...` then
`Pre-flight failed — recovery: light_retry` with growing backoffs; and
`recovery_log.jsonl` gains matching JSON lines. Then delete the test log:
`rm -f recovery_log.jsonl`.

- [ ] **Step 7: Commit**

```bash
git add pipeline.py
git commit -m "feat(pipeline): pre-flight + recovery ladder in default mode, success-rate stats"
```

---

### Task 9: `--persistent` mode in `pipeline.py`; delete `pipeline-persistent.py`

**Files:**
- Modify: `pipeline.py` (add `init_radar`, `capture_once`, `--persistent` flag, teardown)
- Delete: `pipeline-persistent.py`

**Interfaces:**
- Consumes: `mmwcas` (lazy import — only inside persistent-mode functions), `mimo.config_dict`, `utility.check_captured_files/export_config_to_json`, Task 7 `RecoveryPolicy(reinit_fn=...)`.
- Produces: `pipeline.init_radar(tda_ip: str) -> bool`, `pipeline.capture_once(duration: float, tda_ip: str, label: str) -> str | None`, arg `--persistent`.

- [ ] **Step 1: Add persistent-mode capture functions to `pipeline.py`**

Insert after `run_capture` (before the Step 2 section):

```python
# ─────────────────────────────────────────────
# Step 1 (persistent mode) — init once, capture without re-init
# TI's documented 2-phase sequence: heavy init ONCE, then light
# arm→frame→stop→dearm per capture. See TIDEP-01012.md §7.2.
# ─────────────────────────────────────────────

def init_radar(tda_ip: str) -> bool:
    """Heavy phase, done once per process: TDA connect → power-up → firmware
    → RF init calibration → frame config."""
    import mmwcas
    from mimo import config_dict

    _banner('INIT — Radar configure + init (persistent mode, ONCE)')
    status = mmwcas.mmw_set_config(config_dict)
    if status != 0:
        print(f'[PIPELINE] ERROR: mmw_set_config failed (status {status})')
        return False
    status = mmwcas.mmw_init(tda_ip)
    if status != 0:
        print(f'[PIPELINE] ERROR: mmw_init failed (status {status})')
        return False
    time.sleep(2)
    _step('Radar initialised — persistent capture loop ready')
    return True


def capture_once(duration: float, tda_ip: str, label: str) -> str | None:
    """One capture WITHOUT re-init (arm → frame → stop → dearm).
    Returns capture directory name, or None on failure."""
    import mmwcas
    from mimo import config_dict
    from utility import check_captured_files, export_config_to_json

    timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
    capture_dir = f'{label}_{timestamp}'
    _banner(f'STEP 1 — Capture (persistent, {duration}s)  {capture_dir}')

    status = mmwcas.mmw_arming_tda(capture_dir)
    if status != 0:
        print(f'[PIPELINE] mmw_arming_tda failed (status {status})')
        return None
    time.sleep(2)

    status = mmwcas.mmw_start_frame()
    if status != 0:
        print(f'[PIPELINE] mmw_start_frame failed (status {status})')
        mmwcas.mmw_stop_frame()
        mmwcas.mmw_dearming_tda()
        return None

    print(f' Capturing... ({duration}s)', flush=True)
    time.sleep(duration)

    status = mmwcas.mmw_stop_frame()
    if status != 0:
        print(f'[PIPELINE] WARNING: mmw_stop_frame failed (status {status})')
    status = mmwcas.mmw_dearming_tda()
    if status != 0:
        print(f'[PIPELINE] WARNING: mmw_dearming_tda failed (status {status})')

    success, _, _ = check_captured_files(capture_dir, tda_ip)
    if not success:
        print('[PIPELINE] WARNING: no files found on TDA — capture produced no data')
        return None

    json_path = os.path.join(JSON_FILES_DIR, f'{capture_dir}.mmwave.json')
    export_config_to_json(config_dict, json_path)
    return capture_dir
```

- [ ] **Step 2: Add the flag and wire the policy**

Argparse:

```python
    parser.add_argument('--persistent', action='store_true',
                        help='Init the radar ONCE at start; each cycle only does '
                             'arm→frame→stop→dearm (TI 2-phase sequence, avoids the '
                             'per-cycle -8 re-init failures — TIDEP-01012.md §7.2). '
                             'Default off until field-validated.')
```

Replace the policy creation from Task 8 Step 2 with:

```python
    reinit_fn = (lambda: init_radar(args.tda_ip)) if args.persistent else None
    policy = tda_recovery.RecoveryPolicy(args.tda_ip,
                                         reinit_fn=reinit_fn,
                                         power_cycle_cmd=args.power_cycle_cmd)
    stats = {'ok': 0, 'failed': 0}

    if args.persistent:
        while not shutdown_flag and not init_radar(args.tda_ip):
            stats['failed'] += 1
            _step(f'Initial radar init failed — recovery: {policy.on_failure()}')
```

Also add a banner line near the other startup prints:

```python
    print(f'  Capture mode     : {"PERSISTENT (init once)" if args.persistent else "spawn mimo.py per cycle"}')
```

- [ ] **Step 3: Choose the capture path per cycle**

In the main loop, replace the `run_capture` call from Task 8 Step 4 with:

```python
        if args.persistent:
            capture_dir = capture_once(args.duration, args.tda_ip, args.label)
        else:
            capture_dir = run_capture(args.duration, args.tda_ip, args.label)
```

(the failure/success handling below it is unchanged).

- [ ] **Step 4: Teardown on exit**

Before the final `print('\n[PIPELINE] Pipeline stopped cleanly.')` add:

```python
    if args.persistent:
        import mmwcas
        if hasattr(mmwcas, 'mmw_power_off'):
            print('[PIPELINE] Power-off teardown (slaves → master)...')
            try:
                mmwcas.mmw_power_off()
            except Exception as exc:
                print(f'[PIPELINE] WARNING: power-off teardown failed: {exc}')
```

- [ ] **Step 5: Delete the absorbed file and verify**

```bash
git rm pipeline-persistent.py
python3 -m pytest tests/ -v          # all pass
python3 -m py_compile pipeline.py    # compiles
```

Also verify default mode still never imports mmwcas on the Mac:

```bash
python3 -c "import pipeline; print('pipeline importable without mmwcas')"
```

- [ ] **Step 6: Commit**

```bash
git add pipeline.py
git commit -m "feat(pipeline): --persistent init-once mode absorbs pipeline-persistent.py"
```

- [ ] **Step 7: Verify persistent mode on the Raspberry Pi**

```bash
ssh imrsl@imrslpi5-02
cd ~/mmwave-cli && git pull
python3 pipeline.py --persistent --duration 5 --label RelPersist \
    --skip-transfer --skip-ps --skip-lora
# Expected: single INIT banner, then repeated cycles with NO re-init between
# them (~90 s faster per cycle). Ctrl+C → "Power-off teardown" message.
```

---

### Task 10: `mimo.py` light retry with backoff

**Files:**
- Modify: `mimo.py` (add `_try_with_backoff`; use it for arm + start_frame)

**Interfaces:**
- Consumes: nothing new.
- Produces: `mimo._try_with_backoff(fn, name, backoffs=(5, 15, 45)) -> bool` (module-level, reused nowhere else yet). CLI behavior unchanged except failed arm/frame now retries 3× before skipping the loop iteration.

- [ ] **Step 1: Add the helper (after `_now_ms` in `mimo.py`)**

```python
def _try_with_backoff(fn, name, backoffs=(5, 15, 45)):
    """Run fn() -> status up to len(backoffs) times.
    Sleeps backoffs[i] after the i-th failure. True on first success."""
    for i, wait in enumerate(backoffs):
        status = fn()
        if status == 0:
            return True
        last = (i == len(backoffs) - 1)
        print(f'{name} failed (status: {status})'
              + (' — giving up' if last else f' — retrying in {wait}s'))
        if not last:
            time.sleep(wait)
    return False
```

- [ ] **Step 2: Use it for arm**

Replace the arm block in the capture loop:

```python
            # Arm TDA for capture (light retry — see design spec Part 1d)
            print(f"[TS] ARM_TDA_begin   {_now_ms()}", flush=True)
            if not _try_with_backoff(lambda: mmwcas.mmw_arming_tda(capture_dir),
                                     'mmw_arming_tda'):
                continue  # Skip to next loop
            print(f"[TS] ARM_TDA_end     {_now_ms()}", flush=True)
            time.sleep(2)
```

- [ ] **Step 3: Use it for start_frame**

Replace the start-frame block:

```python
            # Start frame capture (light retry)
            print(f"[TS] FRAMING_begin   {_now_ms()}", flush=True)
            if not _try_with_backoff(mmwcas.mmw_start_frame, 'mmw_start_frame'):
                mmwcas.mmw_stop_frame()
                mmwcas.mmw_dearming_tda()
                continue  # Skip to next loop
            # FRAMING_end ≈ t0 of the actual capture (master is triggered last)
            print(f"[TS] FRAMING_end     {_now_ms()}  <-- t0 capture", flush=True)
```

(stop_frame and dearm keep their existing single-attempt handling — a failed
stop after a good capture must not discard the data.)

- [ ] **Step 4: Verify + commit**

Run: `python3 -m py_compile mimo.py` — OK.
On the RPi (with hardware): `python3 mimo.py -t 5 --directory RelRetry` — capture succeeds as before.

```bash
git add mimo.py
git commit -m "feat(mimo): retry arm/start_frame with 5/15/45s backoff before skipping"
```

---

### Task 11: `--finite-framing` option

**Files:**
- Modify: `utility.py` (add `finite_num_frames`)
- Modify: `mimo.py` (flag; set numFrames; skip stop_frame)
- Modify: `pipeline.py` (pass-through flag; persistent-mode support)
- Test: `tests/test_utility.py`

**Interfaces:**
- Consumes: `config_dict['mimo']['frame']` keys.
- Produces: `utility.finite_num_frames(duration_s: float, frame_period_ms: float) -> int`; CLI flag `--finite-framing` on both `mimo.py` and `pipeline.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_utility.py`:

```python
import pytest

from utility import finite_num_frames


def test_exact_multiple():
    assert finite_num_frames(30.0, 30.0) == 1000


def test_rounds_up():
    assert finite_num_frames(10.0, 30.0) == 334


def test_minimum_one_frame():
    assert finite_num_frames(0.001, 30.0) == 1


def test_uint16_guard():
    with pytest.raises(ValueError):
        finite_num_frames(3600.0, 30.0)      # 120000 frames > 65535
```

Note: `utility.py` imports only stdlib + is imported by mimo.py; check the top
of `utility.py` first — if it imports mmwcas at module level, put
`finite_num_frames` in a position where the import stays lazy (it does not, as
of this branch; it only uses subprocess/json/os).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_utility.py -v`
Expected: FAIL with `ImportError: cannot import name 'finite_num_frames'`

- [ ] **Step 3: Implement in `utility.py`**

```python
def finite_num_frames(duration_s: float, frame_period_ms: float) -> int:
    """Frames needed to cover duration_s at frame_period_ms, rounded up (min 1).
    Raises ValueError beyond the AWR2243 uint16 numFrames limit."""
    import math
    n = max(1, math.ceil(duration_s * 1000.0 / frame_period_ms))
    if n > 65535:
        raise ValueError(f'numFrames {n} exceeds uint16 limit 65535 '
                         f'(max duration {65535 * frame_period_ms / 1000.0:.0f}s '
                         f'at {frame_period_ms}ms period)')
    return n
```

Run: `python3 -m pytest tests/test_utility.py -v` — 4 passed.

- [ ] **Step 4: Wire into `mimo.py`**

Argparse:

```python
    parser.add_argument('--finite-framing', action='store_true',
                        help='Program numFrames from --duration (TI official workflow) '
                             'instead of infinite framing + manual StopFrame. '
                             'Eliminates -2 stop-frame errors. Default: off.')
```

After argument validation, before `mmw_set_config`:

```python
    if args.finite_framing:
        from utility import finite_num_frames
        fp = config_dict["mimo"]["frame"]["framePeriodicity"]
        nf = finite_num_frames(args.duration, fp)
        config_dict["mimo"]["frame"]["numFrames"] = nf
        print(f"Finite framing: numFrames={nf} ({args.duration}s @ {fp}ms/frame)")
```

Capture wait + stop: replace `time.sleep(args.duration)` with:

```python
            # Finite framing: frames stop by themselves after numFrames;
            # +2s margin lets the last frame land before de-arm.
            time.sleep(args.duration + (2.0 if args.finite_framing else 0.0))
```

and wrap the stop block:

```python
            if args.finite_framing:
                print(f"[TS] STOP_FRAME skipped (finite framing) {_now_ms()}", flush=True)
            else:
                print(f"[TS] STOP_FRAME      {_now_ms()}", flush=True)
                status = mmwcas.mmw_stop_frame()
                if status != 0:
                    print(f"mmw_stop_frame failed (status: {status})")
                    time.sleep(1)
                    continue  # Skip to next loop
```

- [ ] **Step 5: Wire into `pipeline.py`**

Argparse:

```python
    parser.add_argument('--finite-framing', action='store_true',
                        help='Use finite framing (numFrames from --duration) instead of '
                             'infinite framing + manual StopFrame. Eliminates -2 errors.')
```

Default mode — append to the `cmd` list in `run_capture` (add a parameter):
change the signature to `run_capture(duration, tda_ip, label, finite_framing=False)`
and after the existing `cmd = [...]` add:

```python
    if finite_framing:
        cmd.append('--finite-framing')
```

and the call site: `run_capture(args.duration, args.tda_ip, args.label, args.finite_framing)`.

Persistent mode — in `init_radar`, change the signature to
`init_radar(tda_ip, duration=None, finite_framing=False)` and before
`mmw_set_config` add:

```python
    if finite_framing and duration:
        from utility import finite_num_frames
        fp = config_dict['mimo']['frame']['framePeriodicity']
        config_dict['mimo']['frame']['numFrames'] = finite_num_frames(duration, fp)
```

In `capture_once`, change the signature to
`capture_once(duration, tda_ip, label, finite_framing=False)`; extend the wait
`time.sleep(duration + (2.0 if finite_framing else 0.0))`; and guard the stop:

```python
    if finite_framing:
        print('[PIPELINE] stop_frame skipped (finite framing)')
    else:
        status = mmwcas.mmw_stop_frame()
        if status != 0:
            print(f'[PIPELINE] WARNING: mmw_stop_frame failed (status {status})')
```

Update the persistent call sites:
`init_radar(args.tda_ip, args.duration, args.finite_framing)` (both the reinit
lambda and the startup loop) and
`capture_once(args.duration, args.tda_ip, args.label, args.finite_framing)`.

- [ ] **Step 6: Verify + commit**

Run: `python3 -m pytest tests/ -v` — all pass.
Run: `python3 -m py_compile mimo.py pipeline.py utility.py` — OK.
On the RPi: `python3 mimo.py -t 5 --directory RelFinite --finite-framing` —
capture completes, frame count in the data ≈ 167 (5 s / 30 ms), no -2 error.

```bash
git add utility.py mimo.py pipeline.py tests/test_utility.py
git commit -m "feat: optional --finite-framing (numFrames from duration, no manual StopFrame)"
```

---

### Task 12: Documentation + field verification protocol

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `CLAUDE.md`**

1. **Repository Structure** — add under `pipeline.py`:

```
├── tda_recovery.py                 ← TDA pre-flight + escalating recovery ladder (Step 0)
├── lora_queue.py                   ← LoRa store-and-forward file spool (~/lora_queue/)
```

and delete any `pipeline-persistent.py` mention if present.

2. **Key pipeline arguments table** — add rows:

```
| `--persistent` | off | Init radar ONCE at start; cycles only arm→frame→stop→dearm (TI 2-phase). ~90 s faster/cycle, avoids per-cycle -8. |
| `--power-cycle-cmd` | None | Shell command to hard power-cycle the TDA (relay). Last recovery-ladder level. |
| `--min-tda-free-mb` | `200` | Pre-flight auto-clean of TDA `Trace_TDA_*.txt` below this free space. |
| `--finite-framing` | off | numFrames from duration (TI workflow); eliminates -2 stop-frame errors. |
```

3. **LoRa Uplink section** — append:

```
**Store-and-forward queue (lora_queue.py):** every cycle's metrics are enqueued
to `~/lora_queue/pending/` before sending. Delivery uses confirmed uplinks
(`AT+CMSGHEX`, success = network ACK). On ACK the file moves to `sent/` (newest
200 kept); on failure draining stops and the backlog is retried oldest-first
next cycle (max 20 uplinks/drain, 10 s spacing). `--skip-lora` still enqueues.
Manual tools: `python3 lora_queue.py --status` / `--drain`.
```

4. **Known Issues & Fixes table** — add rows:

```
| ~48% capture failure outdoors (STATUS -8) | Full re-init every cycle (3× -8 chances) | `--persistent` init-once mode + recovery ladder (`tda_recovery.py`) |
| Uplinks lost when gateway/modem down | Unconfirmed send, no retry | Store-and-forward spool + confirmed uplink (`lora_queue.py`) |
| TDA rootfs fills with Trace_TDA_*.txt → total failure | apps.out busy-loop logging | Pre-flight auto-cleanup (`--min-tda-free-mb`) |
```

5. **Common invocations** — add:

```bash
# Persistent mode (init once) + reliability features, 15-min cadence
python3 pipeline.py --persistent --duration 30 --label BridgeSpan --cycle-period 900 \
  --ps-file ~/IoSAR-EdgeProcessing/ps_manual_bridgespan.json
```

- [ ] **Step 2: Field verification protocol (run on RPi before next deployment)**

Not code — execute and record results in the experiment log:

1. **LoRa queue end-to-end:** power off the TTN gateway → run 3 cycles
   (`--duration 10 --skip-transfer --skip-ps`) → `python3 lora_queue.py --status`
   shows 3 pending → power gateway on → next cycle drains all 3 →
   Grafana shows 3 points at their ORIGINAL capture timestamps.
2. **Ladder level 3:** stop `apps.out` on the TDA (`ssh root@tda 'killall apps.out'`)
   → pre-flight must fail (`preflight_apps_down` in recovery_log.jsonl) → ladder
   escalates to `tda_reboot` → board reboots → capture resumes without operator action.
3. **Overnight soak:** `nohup python3 pipeline.py --persistent --duration 15 \
   --label RelSoak --cycle-period 900 --skip-lora > ~/soak.log 2>&1 &` —
   next morning compute success rate from the `Capture success` lines; target
   ≥ 90% (baseline 52%, log 20260510).
4. **Regression:** one full default-mode cycle (no new flags) behaves exactly
   as before.

- [ ] **Step 3: Final check + commit**

Run: `python3 -m pytest tests/ -v` — all pass.

```bash
git add CLAUDE.md
git commit -m "docs: reliability features (recovery ladder, LoRa queue, --persistent)"
```

---

## Self-Review Notes

- Spec coverage: 1a→Task 5, 1b→Tasks 6–7, 1c→Tasks 8–9, 1d→Task 10, 1e→Tasks 6–8 (log_event + stats), 1f→Task 11, 2a→Tasks 1+3, 2b→Task 2, 2c→Task 4, 2d→docs (Task 12), 3a→Tasks 7–8 (never-crash), 3b→per-task verify + Task 12 protocol, 3c→file table matches tasks.
- Deviations from spec (intentional, noted inline): pending filenames get a unix-timestamp prefix (cross-label ordering); pre-flight probes SSH + `pgrep apps.out` instead of TCP 5001 (a connect/close on 5001 could consume apps.out's accept and break the next `mmw_init`).
- `TIDEP-01012.md` line refs in this plan describe the branch point `feat/persistent-pipeline-timestamps`; `mimo.py` line numbers shift after Task 5 — later tasks reference code by content, not line number.
