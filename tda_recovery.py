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
