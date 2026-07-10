import pytest

from utility import finite_num_frames


def test_exact_multiple():
    assert finite_num_frames(30.0, 30.0) == 1000


def test_rounds_up():
    assert finite_num_frames(10.0, 30.0) == 334


def test_minimum_one_frame():
    assert finite_num_frames(0.001, 30.0) == 1


def test_uint16_guard():
    with pytest.raises(ValueError):
        finite_num_frames(3600.0, 30.0)      # 120000 frames > 65535
