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
    bad = os.path.join(spool, 'pending', '0000000001_bad.json')
    with open(bad, 'w') as fh:
        fh.write('{not json')
    sent, remaining = lora_queue.drain(lambda h: True, spool_dir=spool, sleep_fn=lambda s: None)
    assert (sent, remaining) == (1, 0)
    assert os.listdir(os.path.join(spool, 'failed')) == ['0000000001_bad.json']


def test_drain_appends_live_module_temp_when_ser_given(tmp_path, monkeypatch):
    import lora_sender
    spool = str(tmp_path)
    lora_queue.enqueue(_metrics(), spool_dir=spool)
    monkeypatch.setattr(lora_sender, 'read_module_temp', lambda ser: 31.6)

    sent_payloads = []

    def send_fn(hex_payload):
        sent_payloads.append(hex_payload)
        return True

    sent, remaining = lora_queue.drain(send_fn, spool_dir=spool,
                                       sleep_fn=lambda s: None, ser=object())
    assert (sent, remaining) == (1, 0)
    assert bytes.fromhex(sent_payloads[0][-2:]) == (32).to_bytes(1, 'big', signed=True)


def test_drain_without_ser_omits_temp_byte(tmp_path):
    spool = str(tmp_path)
    lora_queue.enqueue(_metrics(), spool_dir=spool)
    sent_payloads = []

    def send_fn(hex_payload):
        sent_payloads.append(hex_payload)
        return True

    lora_queue.drain(send_fn, spool_dir=spool, sleep_fn=lambda s: None)
    assert len(sent_payloads[0]) == 22   # unchanged length — no temp byte appended


def test_drain_quarantines_record_that_breaks_encoding(tmp_path):
    spool = str(tmp_path)
    bad = _metrics('2026-07-04T10:00:00', 'Neg_1')
    bad['dominant_frequency_hz'] = -5.0     # struct.error in encode_payload
    lora_queue.enqueue(bad, spool_dir=spool)
    lora_queue.enqueue(_metrics('2026-07-04T10:01:00', 'Good_2'), spool_dir=spool)
    sent, remaining = lora_queue.drain(lambda h: True, spool_dir=spool, sleep_fn=lambda s: None)
    assert (sent, remaining) == (1, 0)
    assert len(os.listdir(os.path.join(spool, 'failed'))) == 1
