import copy

import pytest

import radar_config

BASE = {
    'mimo': {
        'profile': {'id': 0, 'startFrequency': 77, 'frequencySlope': 90,
                    'idleTime': 3.5, 'adcStartTime': 4.45, 'numAdcSamples': 120,
                    'adcSamplingFrequency': 6500, 'rampEndTime': 23.65,
                    'rxGain': 48, 'txStartTime': 0,
                    'hpfCornerFreq1': 0, 'hpfCornerFreq2': 0},
        'frame': {'numLoops': 10, 'numFrames': 0, 'framePeriodicity': 30},
        'channel': {'rxChannelEn': 0x0F, 'txChannelEn': 0x07},
    }
}


def _write(tmp_path, text):
    p = tmp_path / 'exp.toml'
    p.write_text(text)
    return str(p)


def test_partial_merge_overrides_only_specified(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nfrequencySlope = 65.854\nnumAdcSamples = 512\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['profile']['frequencySlope'] == 65.854
    assert cfg['mimo']['profile']['numAdcSamples'] == 512
    assert cfg['mimo']['profile']['startFrequency'] == 77      # inherited
    assert cfg['mimo']['frame']['framePeriodicity'] == 30      # inherited


def test_frame_and_channel_merge(tmp_path):
    path = _write(tmp_path,
                  '[mimo.frame]\nframePeriodicity = 50\nnumLoops = 16\n'
                  '[mimo.channel]\ntxChannelEn = 0x01\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['frame']['framePeriodicity'] == 50
    assert cfg['mimo']['frame']['numLoops'] == 16
    assert cfg['mimo']['channel']['txChannelEn'] == 1
    assert cfg['mimo']['channel']['rxChannelEn'] == 0x0F       # inherited


def test_c_only_sections_ignored(tmp_path):
    path = _write(tmp_path,
                  '[mimo.profile]\nnumAdcSamples = 256\n\n'
                  '[mimo.tx]\ntx0PhaseShifter = 3\n\n'
                  '[mimo.chirp]\nstartIdx = 0\n')
    cfg = radar_config.load_and_merge(path, BASE)
    assert cfg['mimo']['profile']['numAdcSamples'] == 256
    assert 'tx' not in cfg['mimo']
    assert 'chirp' not in cfg['mimo']


def test_unknown_key_in_profile_errors(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSample = 512\n')   # typo
    with pytest.raises(ValueError, match='numAdcSample'):
        radar_config.load_and_merge(path, BASE)


def test_non_numeric_value_errors(tmp_path):
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSamples = "512"\n')
    with pytest.raises(ValueError, match='numAdcSamples'):
        radar_config.load_and_merge(path, BASE)


def test_missing_file_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        radar_config.load_and_merge(str(tmp_path / 'nope.toml'), BASE)


def test_malformed_toml_errors(tmp_path):
    import tomllib
    path = _write(tmp_path, '[mimo.profile\nnumAdcSamples = 512')
    with pytest.raises(tomllib.TOMLDecodeError):
        radar_config.load_and_merge(path, BASE)


def test_base_not_mutated(tmp_path):
    snapshot = copy.deepcopy(BASE)
    path = _write(tmp_path, '[mimo.profile]\nnumAdcSamples = 999\n')
    radar_config.load_and_merge(path, BASE)
    assert BASE == snapshot
