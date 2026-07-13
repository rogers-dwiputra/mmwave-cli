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
    # No power-cycle relay: the soft-reboot rung is omitted (it halts the
    # TDA2XX with no way back), so the ladder is light-retry only, then restarts.
    pol, sleeps = _policy(tmp_path)          # no reinit_fn, no power_cycle_cmd
    actions = [pol.on_failure() for _ in range(4)]
    assert actions == ['light_retry', 'light_retry', 'light_retry',
                       'ladder_exhausted']
    assert sleeps[:3] == [5, 15, 45]
    assert 600 in sleeps                      # exhausted → long sleep
    assert pol.streak == 0                    # ladder restarted


def test_ladder_persistent_mode_includes_reinit(tmp_path):
    # Persistent mode, no relay: retry + reinit rungs, then exhausted (no reboot).
    reinits = []
    pol, _ = _policy(tmp_path, reinit_fn=lambda: reinits.append(1))
    actions = [pol.on_failure() for _ in range(6)]
    assert actions == ['light_retry', 'light_retry', 'light_retry',
                       'software_reinit', 'software_reinit', 'ladder_exhausted']
    assert len(reinits) == 2


def test_tda_reboot_gated_behind_relay(tmp_path):
    # Without a relay the soft-reboot rung must be absent (it would strand the
    # board); with a relay configured, reboot precedes the power-cycle rung.
    pol_no_relay, _ = _policy(tmp_path)
    assert all(a != 'tda_reboot' for a, _ in pol_no_relay.schedule)
    pol_relay, _ = _policy(tmp_path, power_cycle_cmd='gpio toggle 4')
    assert [a for a, _ in pol_relay.schedule][-2:] == ['tda_reboot', 'power_cycle']


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
    # _wait_board_up is two-phase: first wait for the board to DROP, then wait
    # for it to come back. Sequence: reboot cmd, then up (still up), down,
    # down (booting), up (back).
    cmds = []
    responses = iter([(0, ''),                     # reboot command itself
                      (0, 'UP\n'),                 # phase 1: still up
                      (255, ''),                   # phase 1: dropped
                      (255, ''), (0, 'UP\n')])     # phase 2: booting, then back

    def run(ip, cmd, timeout=30):
        cmds.append(cmd)
        return next(responses)

    # relay configured so the tda_reboot rung is present in the schedule
    pol, sleeps = _policy(tmp_path, run=run, power_cycle_cmd='gpio toggle 4')
    for _ in range(3):
        pol.on_failure()              # burn through light retries
    assert pol.on_failure() == 'tda_reboot'
    # 3 light backoffs + 1×10s still-up + 1×10s booting + 20s post-boot grace
    assert sleeps == [5, 15, 45, 10, 10, 20]
    # The reboot command must be the systemd-aware REBOOT_CMD, not a bare
    # `reboot` (which is not on the TDA's non-interactive PATH — field bug).
    assert cmds[0] == tda_recovery.REBOOT_CMD
    assert 'systemctl reboot' in cmds[0]


def test_wait_board_up_survives_raising_run(tmp_path):
    calls = []
    def raising_run(ip, cmd, timeout=30):
        calls.append(cmd)
        if cmd != 'echo UP':          # the reboot command
            return 0, ''
        if len(calls) < 4:
            raise RuntimeError('ssh blew up')
        return 0, 'UP\n'
    pol, sleeps = _policy(tmp_path, run=raising_run, power_cycle_cmd='gpio toggle 4')
    for _ in range(3):
        pol.on_failure()
    assert pol.on_failure() == 'tda_reboot'   # must not raise
    assert 20 in sleeps                        # post-boot grace still applied


def test_log_event_never_raises_on_unwritable_path(tmp_path, capsys):
    bad = str(tmp_path / 'no_such_dir' / 'rec.jsonl')
    tda_recovery.log_event('light_retry', 'x', path=bad)   # must not raise
    assert '[RECOVERY] light_retry' in capsys.readouterr().out
