import math

import pytest

from dex1_rs485.motion import plan_ramp
from dex1_rs485.protocol import STATUS_LOCK


def statuses(hand):
    return {(f[2] >> 4) & 0x7 for f in hand.sent[-6:]}


def test_plan_ramp_is_monotonic_and_ends_on_target():
    ramp = plan_ramp(0.0, 2.0, 2.0, 0.04)
    assert ramp[-1] == pytest.approx(2.0) and ramp == sorted(ramp) and len(ramp) == 50


def test_move_up_and_back(ctrl, hand):
    up = ctrl.move_to(5.0, 3.0)
    assert up.ok and up.peak_rad > 4.0
    down = ctrl.move_to(0.1, 3.0)
    assert down.ok and down.end_rad < 0.3
    assert STATUS_LOCK in statuses(hand)  # braked before the final read


def test_speed_limit_lengthens_the_ramp(ctrl):
    assert ctrl.ramp_time(0.0, 5.0, 1.0) == pytest.approx(math.pi / 2 * 5.0 / ctrl.limits.max_speed_rad_s)
    assert ctrl.ramp_time(0.0, 0.1, 0.1) == ctrl.limits.min_ramp_s


def test_targets_outside_the_limits_are_refused_before_anything_is_sent(ctrl, hand):
    n = len(hand.sent)
    with pytest.raises(ValueError):
        ctrl.move_to(ctrl.limits.open_limit_rad + 0.01)
    with pytest.raises(ValueError):
        ctrl.move_to(ctrl.limits.position_min_rad - 0.01)
    assert len(hand.sent) == n


def test_uncalibrated_start_is_refused(ctrl, hand):
    hand.q = 9.0
    with pytest.raises(ValueError, match="calibrate"):
        ctrl.move_to(1.0)


def test_missed_replies_abort_and_brake(ctrl, hand):
    hand.silent_after = len(hand.sent) + 1 + 5  # answers the start read and 5 steps, then goes silent
    result = ctrl.move_to(2.0, 2.0)
    assert not result.ok and "missed" in result.reason
    assert STATUS_LOCK in statuses(hand)


def test_over_temperature_aborts(ctrl, hand):
    hand.temp = ctrl.limits.max_temp_c + 1
    assert "temperature" in ctrl.move_to(2.0, 2.0).reason


def test_merror_aborts(ctrl, hand):
    hand.merror = 0x8
    assert "MError" in ctrl.move_to(2.0, 2.0).reason


def test_stuck_finger_aborts_on_tracking_error(ctrl, hand):
    hand.stuck = True
    result = ctrl.move_to(3.0, 2.0)
    assert not result.ok and "from the command" in result.reason


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 0.0, -1.0, 1e9])
def test_ramp_time_rejects_bad_requests(ctrl, bad):
    with pytest.raises(ValueError):
        ctrl.ramp_time(0.0, 1.0, bad)
