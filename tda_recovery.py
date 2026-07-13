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
# MANDATED DEVIATION (2026-07-09): busybox on the TDA has no pgrep — use ps|grep.
PREFLIGHT_CMD = ("ps w | grep -v grep | grep -q apps.out && echo APPS_OK || echo APPS_DOWN; "
                 "df -k / | tail -1")


def log_event(action, detail='', streak=None, path=None):
    """Append one structured recovery event to recovery_log.jsonl."""
    rec = {'ts': datetime.now().isoformat(timespec='seconds'),
           'action': action, 'detail': detail}
    if streak is not None:
        rec['streak'] = streak
    note = ''
    try:
        with open(path or RECOVERY_LOG, 'a') as fh:
            fh.write(json.dumps(rec) + '\n')
    except OSError as exc:
        note = f'  (log write failed: {exc})'
    print(f'[RECOVERY] {action}  {detail}{note}', flush=True)


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


LIGHT_BACKOFFS_S = (5, 15, 45)
REINIT_ATTEMPTS = 2
REBOOT_WAIT_S = 180
SHUTDOWN_WAIT_S = 60      # after issuing reboot, wait this long for the board to actually drop
BOOT_POLL_S = 10
POST_BOOT_GRACE_S = 20
LADDER_EXHAUSTED_SLEEP_S = 600

# The TDA runs systemd with a bare login PATH over non-interactive SSH, so a plain
# `reboot` is "command not found" (rc 127, /sbin not on PATH) and silently no-ops
# (field-verified 2026-07-13). systemctl (in /bin) works; the rest are forced fallbacks.
REBOOT_CMD = ('systemctl reboot -i 2>/dev/null'
              ' || /sbin/reboot -f 2>/dev/null'
              ' || reboot -f 2>/dev/null'
              ' || echo b > /proc/sysrq-trigger')


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
        # The soft reboot rung is gated behind a configured power-cycle relay.
        # On the TDA2XX, `systemctl reboot` HALTS the board without bringing it
        # back (field-verified 2026-07-13) — so with no relay to recover it, a
        # reboot would strand the radar until a manual power-cycle. Only arm the
        # reboot rung when the relay that follows it can revive a board that
        # fails to return. Without a relay the ladder is retry/reinit only, then
        # ladder_exhausted (which sleeps and restarts) — the board stays alive.
        if self.power_cycle_cmd:
            sched.append(('tda_reboot', None))
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
                rc, _out = self.run(self.tda_ip, REBOOT_CMD)
                if rc != 0:
                    log_event('tda_reboot_cmd_nonzero', f'rc={rc}',
                              path=self.log_path)
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
        """After issuing a reboot/power-cycle: first wait for the board to
        actually go DOWN, then poll until it answers again, then give apps.out
        a grace period to start listening.

        The down-wait matters: a reboot takes a few seconds to sever SSH, so
        without it the first up-poll sees the not-yet-rebooted board, returns
        immediately, and the ladder proceeds as if the reboot completed
        (field-verified failure mode, 2026-07-13). The down-wait is bounded, so
        a reboot command that never takes effect only costs SHUTDOWN_WAIT_S."""
        # Phase 1 — wait for the board to drop.
        for _ in range(SHUTDOWN_WAIT_S // BOOT_POLL_S):
            try:
                rc, _out = self.run(self.tda_ip, 'echo UP', timeout=BOOT_POLL_S)
            except Exception:
                rc = 255
            if rc != 0:
                break  # board is down — reboot is under way
            self.sleep(BOOT_POLL_S)
        # Phase 2 — wait for the board to come back.
        for _ in range(REBOOT_WAIT_S // BOOT_POLL_S):
            try:
                rc, _out = self.run(self.tda_ip, 'echo UP', timeout=BOOT_POLL_S)
            except Exception:
                rc = 255  # board still down (or run() itself is broken) — keep polling
            if rc == 0:
                break
            self.sleep(BOOT_POLL_S)
        self.sleep(POST_BOOT_GRACE_S)
