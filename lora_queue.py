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


def drain(send_fn, spool_dir=None, max_send=20, spacing_s=10.0, sleep_fn=time.sleep, ser=None):
    """
    Send pending messages oldest-first via send_fn(hex_payload) -> bool.
    Stops at the first failure (link considered down) or after max_send.
    Corrupt files are moved to failed/ so they never block the queue.
    `ser`, if given (an open, joined Wio-E5 session), is queried once via
    AT+TEMP and the reading is stamped onto every payload sent this drain.
    Returns (sent_count, remaining_count).
    """
    # lazy: keeps lora_queue importable without pyserial
    from lora_sender import encode_payload, read_module_temp
    _, _, failed_dir = _dirs(spool_dir)
    module_temp_c = read_module_temp(ser) if ser is not None else None
    sent_count = 0
    for path in list_pending(spool_dir):
        if sent_count >= max_send:
            print(f'[QUEUE] max_send={max_send} reached — remaining backlog drains next cycle')
            break
        try:
            with open(path) as fh:
                metrics = json.load(fh)
            hex_payload = encode_payload(metrics, module_temp_c=module_temp_c)
        except Exception as exc:
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
                lambda h: lora_sender.send_payload_confirmed(ses, h), ser=ses)
        finally:
            ses.close()
        print(f'drained: {sent} sent, {remaining} pending')
    else:
        print(f'pending: {len(list_pending())}')
