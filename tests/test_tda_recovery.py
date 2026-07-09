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
