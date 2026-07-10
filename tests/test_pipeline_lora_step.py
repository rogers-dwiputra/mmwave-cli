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


def test_happy_path_sends_and_drains_queue(tmp_path, monkeypatch):
    import lora_sender

    class _DummySession:
        def close(self):
            pass

    monkeypatch.setattr(lora_queue, 'DEFAULT_SPOOL_DIR', str(tmp_path / 'spool'))
    monkeypatch.setattr(pipeline, 'EDGE_DIR', str(tmp_path))
    monkeypatch.setattr(lora_sender, 'open_session', lambda **kw: _DummySession())
    monkeypatch.setattr(lora_sender, 'send_payload_confirmed', lambda ses, h: True)
    cap = 'T_260704_100002'
    _write_metrics(tmp_path, cap)
    ok = pipeline.run_lora_step(cap, port='/dev/null', appkey='X')
    assert ok is True
    assert len(lora_queue.list_pending()) == 0


def test_enqueue_failure_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(lora_queue, 'DEFAULT_SPOOL_DIR', str(tmp_path / 'spool'))
    monkeypatch.setattr(pipeline, 'EDGE_DIR', str(tmp_path))

    def _raise(*a, **kw):
        raise OSError('disk full')

    monkeypatch.setattr(lora_queue, 'enqueue', _raise)
    cap = 'T_260704_100003'
    _write_metrics(tmp_path, cap)
    ok = pipeline.run_lora_step(cap, port='/dev/null', appkey='X')
    assert ok is False
