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
