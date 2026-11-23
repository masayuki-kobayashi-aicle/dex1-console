"""Auto zero (close until the finger stops, call that 0) and the per-move strength, against the mock hand."""
import struct

import pytest

from dex1_rs485.calibrate import auto_zero
from dex1_rs485.config import Limits
from dex1_rs485.jsonl_log import NullLog
from dex1_rs485.link import Link
from dex1_rs485.mock import MockHand
from dex1_rs485.motion import Controller, NoPacer
from dex1_rs485.protocol import STATUS_LOCK


def k_pos(frame: bytes) -> int:
    return struct.unpack("<H", frame[12:14])[0]


def is_brake(frame: bytes) -> bool:
    return (frame[2] >> 4) & 7 == STATUS_LOCK


def test_auto_zero_sets_the_closed_stop_as_zero(ctrl, hand):
    hand.q = 2.0
    result = auto_zero(ctrl)
    assert result.ok and result.reason == ""
    assert result.zero_rad == pytest.approx(-0.06, abs=0.01)  # where the mock's closed stop is
    assert result.travel_rad == pytest.approx(2.06, abs=0.05)
    assert abs(ctrl.read_state().output_rad) < 0.01
    assert any(is_brake(f) for f in hand.sent)  # the hand is braked once it has stopped


def test_after_auto_zero_commands_and_readings_both_use_the_new_zero(ctrl, hand):
    auto_zero(ctrl)
    moved = ctrl.move_to(1.0)
    assert moved.ok and moved.end_rad == pytest.approx(1.0, abs=0.05)
    assert hand.q == pytest.approx(1.0 + ctrl.link.zero_rad, abs=0.05)  # the hand itself is at 1.0 above its own stop


def test_the_closing_push_is_bounded_by_the_lead_and_the_zero_gain(ctrl, hand):
    hand.q = 1.0
    auto_zero(ctrl)
    lim = ctrl.limits
    steps = [f for f in hand.sent if not is_brake(f) and k_pos(f) > 0]
    assert steps and all(k_pos(f) == lim.zero_kp_raw for f in steps)
    lowest = min(struct.unpack("<i", f[8:12])[0] for f in steps) * 2 * 3.141592653589793 / (25.0 * 32768)
    assert lowest >= -0.06 - lim.zero_lead_rad - 0.01  # never further past the stop than the lead


def test_a_stop_far_from_the_expected_closed_position_is_refused(ctrl, hand):
    hand.q, hand.stuck = 3.0, True  # something holds the finger open
    result = auto_zero(ctrl)
    assert not result.ok and "blocking" in result.reason
    assert ctrl.link.zero_rad == 0.0 and any(is_brake(f) for f in hand.sent)


def test_cancel_stops_the_search_and_keeps_the_old_zero(cfg, hand):
    ctrl = Controller(Link(hand, 7, log=NullLog()), cfg.hand, cfg.limits, pacer_factory=NoPacer, cancel=lambda: True)
    hand.q = 3.0
    result = auto_zero(ctrl)
    assert not result.ok and "interrupted" in result.reason and ctrl.link.zero_rad == 0.0
    assert any(is_brake(f) for f in hand.sent)


def test_a_failed_search_restores_the_previous_zero(ctrl, hand):
    ctrl.link.zero_rad = 0.2
    hand.q = 3.0
    hand.stuck = True
    assert not auto_zero(ctrl).ok
    assert ctrl.link.zero_rad == 0.2


def test_strength_scales_the_gain_and_is_limited(ctrl, hand):
    assert ctrl.kp_from_pct(100) == ctrl.hand.kp_raw
    assert ctrl.kp_from_pct(50) == round(ctrl.hand.kp_raw / 2)
    for bad in (0, 5, 101, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ctrl.kp_from_pct(bad)
    ctrl.move_to(2.0, kp_raw=ctrl.kp_from_pct(30))
    steps = [f for f in hand.sent if not is_brake(f) and k_pos(f) > 0]
    assert steps and {k_pos(f) for f in steps} == {ctrl.kp_from_pct(30)}


def test_limits_reject_inconsistent_strength_or_zero_settings():
    with pytest.raises(ValueError):
        Limits(min_strength_pct=50, max_strength_pct=20)
    with pytest.raises(ValueError):
        Limits(zero_kp_raw=0)
    with pytest.raises(ValueError):
        Limits(zero_speed_rad_s=0)
