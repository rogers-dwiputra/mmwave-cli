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
