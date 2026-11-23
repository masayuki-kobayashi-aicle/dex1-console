"""Safe motion: cosine ramps with a check on every reply. Any anomaly brakes the hand and stops."""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import HandConfig, Limits
from .i18n import t
from .link import Link, LinkError
from .protocol import Reply, build_idle, build_lock, build_position


class Pacer:
    """Keeps the control loop at limits.step_s. Tests replace it with one that does not wait."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def wait_until(self, offset_s: float) -> None:
        time.sleep(max(0.0, self._t0 + offset_s - time.monotonic()))


class NoPacer(Pacer):
    def wait_until(self, offset_s: float) -> None:
        pass


@dataclass(frozen=True)
class MoveResult:
    ok: bool
    reason: str  # empty when ok; otherwise why the move stopped
    start_rad: float
    end_rad: float
    peak_rad: float
    duration_s: float  # planned


def plan_ramp(q0: float, target: float, ramp_s: float, step_s: float) -> list[float]:
    """Cosine ease from q0 to target, one value per control step (the last equals target)."""
    n = max(1, round(ramp_s / step_s))
    return [q0 + (target - q0) * (1 - math.cos(math.pi * i / n)) / 2 for i in range(1, n + 1)]


def check_reply(reply: Reply, motor_id: int, limits: Limits, target: float | None) -> str:
    """A reason to abort, or an empty string."""
    if reply.motor_id != motor_id:
        return t("reply_wrong_id", got=reply.motor_id, want=motor_id)
    if reply.merror:
        return t("merror", code=reply.merror)
    if max(reply.temp_case, reply.temp_coil) > limits.max_temp_c:
        return t("over_temp", case=reply.temp_case, coil=reply.temp_coil, limit=limits.max_temp_c)
    if target is not None and abs(reply.output_rad - target) > limits.max_track_err_rad:
        return t("track_err", q=reply.output_rad, err=abs(reply.output_rad - target), target=target)
    return ""


class Controller:
    def __init__(self, link: Link, hand: HandConfig, limits: Limits, pacer_factory: Callable[[], Pacer] = Pacer,
                 say: Callable[[str], None] = lambda msg: None, cancel: Callable[[], bool] = lambda: False) -> None:
        self.link, self.hand, self.limits = link, hand, limits
        self._pacer_factory, self.say, self.cancel = pacer_factory, say, cancel  # cancel(): True asks a move to stop (GUI)

    def read_state(self, kind: str = "status") -> Reply:
        """Zero-gain read: no torque. Raises LinkError after limits.max_missed_replies misses in a row."""
        for n in range(self.limits.max_missed_replies):
            reply = self.link.txrx(build_idle(self.hand.motor_id), kind, n=n)
            if reply is not None:
                return reply
        raise LinkError(t("link_error", id=self.hand.motor_id, n=self.limits.max_missed_replies))

    def brake(self) -> None:
        for n in range(self.limits.brake_repeats):
            self.link.txrx(build_lock(self.hand.motor_id), "brake", n=n)

    def ramp_time(self, q0: float, target: float, ramp_s: float | None, speed_rad_s: float | None = None) -> float:
        """Requested time (or the time that gives the requested peak speed), raised so the peak speed
        (pi/2 * distance / time) stays within limits.max_speed_rad_s."""
        lim = self.limits
        distance = abs(target - q0)
        needed = math.pi / 2 * distance / lim.max_speed_rad_s
        if speed_rad_s is not None:
            if ramp_s is not None:
                raise ValueError(t("ramp_and_speed"))
            wanted = lim.check_ramp(max(math.pi / 2 * distance / lim.check_speed(speed_rad_s), lim.min_ramp_s))
        else:
            wanted = lim.default_ramp_s if ramp_s is None else lim.check_ramp(ramp_s)
        return max(wanted, lim.min_ramp_s, needed)

    def kp_from_pct(self, pct: float) -> int:
        """Position gain for a strength in percent of hand.kp_raw (checked against the limits)."""
        return max(1, round(self.hand.kp_raw * self.limits.check_strength(pct) / 100))

    def move_to(self, target: float, ramp_s: float | None = None, kp_raw: int | None = None,
                speed_rad_s: float | None = None) -> MoveResult:
        """Move the output axis to target [rad]. Always ends with a brake. Never raises for hand anomalies: see MoveResult.

        kp_raw: position gain for this move (default hand.kp_raw). Lower is softer; the hand may then lag and trip max_track_err_rad.
        speed_rad_s: peak speed instead of a time (not both). The move time is derived from the distance."""
        lim = self.limits
        if not lim.position_min_rad <= target <= lim.open_limit_rad:
            raise ValueError(t("target_out", t=target, lo=lim.position_min_rad, hi=lim.open_limit_rad))
        q0 = self.read_state("start").output_rad
        if not lim.position_min_rad - lim.start_slack_rad <= q0 <= lim.open_limit_rad + lim.start_slack_rad:
            raise ValueError(t("uncalibrated", q=q0))
        ramp = self.ramp_time(q0, target, ramp_s, speed_rad_s)
        self.say(t("move_plan", q0=q0, target=target, ramp=ramp))
        reason, peak, misses, pacer = "", q0, 0, self._pacer_factory()
        try:
            for i, tq in enumerate(plan_ramp(q0, target, ramp, lim.step_s), start=1):
                reply = self.link.txrx(build_position(self.hand.motor_id, tq + self.link.zero_rad, kp_raw or self.hand.kp_raw, self.hand.kd_raw),
                                       "step", step=i, target=round(tq, 4))
                misses = misses + 1 if reply is None else 0
                if misses >= lim.max_missed_replies:
                    reason = t("misses", n=misses)
                    break
                if reply is not None:
                    peak = max(peak, reply.output_rad)
                    reason = check_reply(reply, self.hand.motor_id, lim, tq)
                    if reason:
                        break
                if self.cancel():
                    reason = t("interrupted")
                    break
                pacer.wait_until(i * lim.step_s)
        except KeyboardInterrupt:
            reason = t("interrupted")
        finally:
            self.brake()
        end = q0
        try:
            end = self.read_state("end").output_rad
        except LinkError:
            reason = reason or t("no_reply_after")
        return MoveResult(not reason, reason, q0, end, peak, ramp)
