import pytest

from dex1_rs485 import protocol as p
from dex1_rs485.cli import SELFTEST_FRAMES, selftest


def test_frames_match_the_vendor_sdk():
    for name, (want, make) in SELFTEST_FRAMES.items():
        assert make().hex(" ") == want, name
    assert selftest() == 0


def test_control_frame_validates_input():
    with pytest.raises(ValueError):
        p.build_control(16, 1, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        p.build_control(7, 2, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError):
        p.crc32_core(b"abc")


def test_reply_roundtrip_all_crc_variants():
    for variant in p.REPLY_CRC_VARIANTS:
        frame = p.build_reply(7, 1.234, temp_case=33, temp_coil=29, volts=24.5, variant=variant)
        reply, used = p.find_reply(frame)
        assert reply is not None and used == p.REPLY_LEN
        assert variant in reply.crc_variants
        assert reply.motor_id == 7 and reply.temp_case == 33 and reply.volts == 24.5
        assert reply.output_rad == pytest.approx(1.234, abs=1e-3)


def test_find_reply_skips_garbage_and_waits_for_a_complete_frame():
    frame = p.build_reply(7, 0.5)
    reply, _ = p.find_reply(b"\x00\xfc\xee\x01" + frame)
    assert reply is not None and reply.motor_id == 7
    assert p.find_reply(frame[:-3])[0] is None
    corrupt = frame[:-1] + bytes([frame[-1] ^ 1])
    assert p.find_reply(corrupt)[0] is None


def test_pos_raw_truncates_toward_zero():
    assert p.pos_raw(0.0) == 0
    assert p.pos_raw(0.10) == 13037
    assert p.pos_raw(-0.10) == -13037
