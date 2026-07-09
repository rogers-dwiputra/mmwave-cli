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
