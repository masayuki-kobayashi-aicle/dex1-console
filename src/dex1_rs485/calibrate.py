"""Auto zero: close the hand slowly until the finger stops against the closed stop, and call that position 0.

This sets a software zero on the Link for the rest of the session. It does not write the hand's own calibration (the frame
for that is not known) and nothing is saved: run it again after reconnecting. Every number used here (speed, gain, how far
ahead the target may be) is a choice, not a measurement on the hand; the push on the stop is bounded by zero_lead_rad and
zero_kp_raw, and the Stop button or Ctrl-C brakes at once.
"""
from __future__ import annotations

import itertools
import statistics
from collections import deque
from dataclasses import dataclass

from .i18n import t
from .link import LinkError
from .motion import Controller, check_reply
from .protocol import build_position

EXTRA_TRAVEL_RAD = 1.0  # beyond the full stroke the search gives up
END_READS = 3


@dataclass(frozen=True)
class ZeroResult:
    ok: bool
    reason: str  # empty when ok
    zero_rad: float  # the zero in effect afterwards (in the hand's own angle)
    travel_rad: float


def auto_zero(ctrl: Controller) -> ZeroResult:
    """Close until the finger stops and set the zero there. The hand ends braked. Stop (the cancel hook) interrupts it."""
    link, lim = ctrl.link, ctrl.limits
    old = link.zero_rad
    link.zero_rad = 0.0  # search in the hand's own angle
    try:
        q0, stop, reason = _close_until_stopped(ctrl)
    except BaseException:
        link.zero_rad = old
        raise
    travel = q0 - stop if stop is not None else 0.0
    if stop is None:
        link.zero_rad = old
        return ZeroResult(False, reason, old, 0.0)
    in_range = lim.position_min_rad - lim.start_slack_rad <= q0 - old <= lim.open_limit_rad + lim.start_slack_rad
    if in_range and abs(stop - old - lim.expected_closed_rad) > lim.zero_tolerance_rad:
        link.zero_rad = old
        return ZeroResult(False, t("zero_implausible", q=stop - old, exp=lim.expected_closed_rad, tol=lim.zero_tolerance_rad),
                          old, travel)
    link.zero_rad = stop
    return ZeroResult(True, "", stop, travel)


def _close_until_stopped(ctrl: Controller) -> tuple[float, float | None, str]:
    """(start angle, stop angle or None, reason when None). Angles in the hand's own frame; ends with a brake."""
    lim, hand, link = ctrl.limits, ctrl.hand, ctrl.link
    q0 = ctrl.read_state("zero_start").output_rad
    window: deque[float] = deque(maxlen=max(2, round(lim.zero_stall_s / lim.step_s)))
    floor = q0 - (lim.open_limit_rad - lim.position_min_rad + EXTRA_TRAVEL_RAD)
    ctrl.say(t("zero_plan", q0=q0, speed=lim.zero_speed_rad_s))
    pacer, target, q, misses, reason, stop = ctrl._pacer_factory(), q0, q0, 0, "", None
    try:
        for i in itertools.count(1):
            target = max(target - lim.zero_speed_rad_s * lim.step_s, q - lim.zero_lead_rad)  # never further ahead than the lead
            if target < floor:
                reason = t("zero_no_stop")
                break
            reply = link.txrx(build_position(hand.motor_id, target, lim.zero_kp_raw, hand.kd_raw), "zero", step=i, target=round(target, 4))
            misses = misses + 1 if reply is None else 0
            if misses >= lim.max_missed_replies:
                reason = t("misses", n=misses)
                break
            if reply is not None:
                q = reply.output_rad
                reason = check_reply(reply, hand.motor_id, lim, None)
                window.append(q)
                if reason:
                    break
                if len(window) == window.maxlen and max(window) - min(window) < lim.zero_stall_move_rad and q - target >= 0.9 * lim.zero_lead_rad:
                    stop = q
                    break
            if ctrl.cancel():
                reason = t("interrupted")
                break
            pacer.wait_until(i * lim.step_s)
    except KeyboardInterrupt:
        reason = t("interrupted")
    finally:
        ctrl.brake()
    if stop is not None:
        reads = []
        for _ in range(END_READS):
            try:
                reads.append(ctrl.read_state("zero_end").output_rad)
            except LinkError:
                break
        stop = statistics.median(reads) if reads else stop
    return q0, stop, reason
