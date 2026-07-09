import lora_sender


class FakeSerial:
    """Scripted Wio-E5. script: dict {command-prefix: [response lines]}.
    Longest matching prefix wins ('AT+JOIN' beats 'AT')."""

    def __init__(self, script):
        self.script = script
        self.buffer = []
        self.written = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.buffer)

    def write(self, data):
        cmd = data.decode().strip()
        self.written.append(cmd)
        key = max((k for k in self.script if cmd.startswith(k)), key=len, default=None)
        self.buffer = [l + '\r\n' for l in self.script.get(key, ['OK'])]

    def readline(self):
        return self.buffer.pop(0).encode()

    def reset_input_buffer(self):
        self.buffer = []

    def flush(self):
        pass

    def close(self):
        self.closed = True


JOIN_OK = {
    'AT+KEY': ['+KEY: APPKEY'],
    'AT+ADR': ['+ADR: ON'],
    'AT+DR': ['+DR: DR5'],
    'AT+JOIN': ['+JOIN: Network joined', '+JOIN: Done'],
    'AT': ['+AT: OK'],
}


def _no_sleep(monkeypatch):
    monkeypatch.setattr(lora_sender.time, 'sleep', lambda s: None)


def test_open_session_joins(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial(JOIN_OK)
    ses = lora_sender.open_session(ser_factory=lambda: fake)
    assert ses is fake
    assert any(w.startswith('AT+JOIN') for w in fake.written)


def test_open_session_join_failed_returns_none(monkeypatch):
    _no_sleep(monkeypatch)
    script = dict(JOIN_OK)
    # '+JOIN: Join failed' alone doesn't match expected='joined' nor the
    # ERROR/+ERR terminal tokens _send_at checks for, so it would otherwise
    # spin for the full 30 s timeout (twice: JOIN then JOIN=FORCE). Add a
    # trailing ERROR line so _send_at's existing early-exit path fires.
    script['AT+JOIN'] = ['+JOIN: Join failed', '+JOIN: ERROR']
    fake = FakeSerial(script)
    ses = lora_sender.open_session(ser_factory=lambda: fake)
    assert ses is None
    assert fake.closed


def test_send_confirmed_ack(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial({'AT+CMSGHEX': ['+CMSGHEX: Start', '+CMSGHEX: Wait ACK',
                                      '+CMSGHEX: ACK Received', '+CMSGHEX: Done']})
    assert lora_sender.send_payload_confirmed(fake, 'AABB', timeout=0.5) is True


def test_send_confirmed_no_ack_is_failure(monkeypatch):
    _no_sleep(monkeypatch)
    fake = FakeSerial({'AT+CMSGHEX': ['+CMSGHEX: Start', '+CMSGHEX: Done']})
    assert lora_sender.send_payload_confirmed(fake, 'AABB', timeout=0.5) is False
