"""A move can be requested by peak speed instead of time (the cosine ramp peaks at pi/2 * distance / time)."""
import math

import pytest

from dex1_rs485.config import Limits
from test_gui import call, gui, run_preflight, wait_idle  # noqa: F401  (fixture and helpers)


def test_speed_gives_the_matching_ramp_time(ctrl):
    assert ctrl.ramp_time(0.1, 5.1, None, 1.0) == pytest.approx(math.pi / 2 * 5.0 / 1.0)
    assert ctrl.ramp_time(0.1, 5.1, None, 0.5) == pytest.approx(math.pi / 2 * 5.0 / 0.5)


def test_a_short_move_is_never_faster_than_the_minimum_ramp(ctrl):
    assert ctrl.ramp_time(2.0, 2.01, None, 1.5) == ctrl.limits.min_ramp_s


def test_speed_above_the_limit_or_not_a_number_is_refused(ctrl):
    for bad in (0, -1, ctrl.limits.max_speed_rad_s + 0.1, math.nan, math.inf):
        with pytest.raises(ValueError):
            ctrl.ramp_time(0.1, 5.1, None, bad)


def test_time_and_speed_together_are_refused(ctrl):
    with pytest.raises(ValueError):
        ctrl.ramp_time(0.1, 5.1, 5.0, 1.0)


def test_a_speed_too_slow_for_the_longest_ramp_is_refused(ctrl):
    slowest = math.pi / 2 * 5.0 / ctrl.limits.max_ramp_s
    with pytest.raises(ValueError):
        ctrl.ramp_time(0.1, 5.1, None, slowest * 0.5)


def test_move_to_with_speed_takes_the_derived_time(ctrl, hand):
    hand.q = 1.0
    result = ctrl.move_to(2.0, speed_rad_s=1.0)
    assert result.ok and result.duration_s == pytest.approx(math.pi / 2, abs=1e-3)  # the start is read from the hand, which quantises


def test_gui_speed_is_checked_and_excludes_ramp(gui):  # noqa: F811
    run_preflight(gui)
    assert call(gui, "go", {"to": 2.0, "speed": 1.0})[0] == 202
    wait_idle(gui)
    for bad in ({"speed": 0}, {"speed": 9}, {"speed": "x"}, {"speed": True}, {"speed": 1.0, "ramp_s": 3.0}):
        assert call(gui, "go", {"to": 2.0, **bad})[0] == 400
    assert gui.session.state()["limits"]["max_speed_rad_s"] == Limits().max_speed_rad_s
