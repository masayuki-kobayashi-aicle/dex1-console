"""Preflight: environment, link, state, calibration (the hand closes itself, a person checks by eye), small motion.

Stops at the first failing stage and says how to fix it. It never writes the calibration; that is a separate procedure.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .calibrate import auto_zero
from .i18n import t
from .link import LinkError
from .motion import Controller
from .prompter import Prompter
from .protocol import build_idle

PROBES = 10
MIN_REPLY_RATE = 0.9
MAX_MEDIAN_FIRST_RX_MS = 50.0  # host-side timing including USB latency; it varies 1-16 ms. Missing replies are the real signal
VOLT_RANGE = (22.0, 26.0)
PREFLIGHT_MAX_TEMP_C = 50
SMALL_MOVE_RAD = 0.5
PREFLIGHT_STAGES = 5  # a run that passed has this many stages
NO_ANSWERS = ("n", "no", "いいえ", "ｎ")


@dataclass(frozen=True)
class Stage:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _show(say, stage: Stage) -> bool:
    fix = f"\n        {t('pf_fix')}{stage.fix}" if not stage.ok and stage.fix else ""
    say(f"  {t('pf_pass') if stage.ok else t('pf_fail')}  {stage.name}: {stage.detail}{fix}")
    return stage.ok


def run_preflight(ctrl: Controller, io: Prompter) -> list[Stage]:
    """Returns the stages run (the last one failed unless every stage passed)."""
    stages: list[Stage] = []

    def record(stage: Stage) -> bool:
        stages.append(stage)
        return _show(io.say, stage)

    io.say(t("pf_title"))
    ok, detail, fix = ctrl.link.transport.check_environment()
    if not record(Stage(t("st_env"), ok, detail, fix)):
        return stages
    got, delays = [], []
    for _ in range(PROBES):
        reply = ctrl.link.txrx(build_idle(ctrl.hand.motor_id), "preflight")
        if reply is not None:
            got.append(reply)
            delays.append(ctrl.link.last_first_rx_ms)
    seen = [d for d in delays if d is not None]
    median = statistics.median(seen) if seen else 0.0
    link_ok = len(got) / PROBES >= MIN_REPLY_RATE and median <= MAX_MEDIAN_FIRST_RX_MS
    if not record(Stage(t("st_link"), link_ok, t("link_detail", n=len(got), total=PROBES, ms=median), t("link_fix"))):
        return stages
    last = got[-1]
    lim = ctrl.limits
    state_ok = (last.motor_id == ctrl.hand.motor_id and last.merror == 0 and max(last.temp_case, last.temp_coil) <= PREFLIGHT_MAX_TEMP_C
                and VOLT_RANGE[0] <= last.volts <= VOLT_RANGE[1])
    if not record(Stage(t("st_state"), state_ok, t("state_detail", id=last.motor_id, m=last.merror, c=last.temp_case, k=last.temp_coil, v=last.volts),
                        t("state_fix"))):
        return stages
    old_zero = ctrl.link.zero_rad
    try:
        zero = auto_zero(ctrl)
        q = ctrl.read_state("calibration").output_rad if zero.ok else 0.0
    except LinkError as e:
        record(Stage(t("st_cal"), False, str(e), t("link_fix")))
        return stages
    if not zero.ok:
        record(Stage(t("st_cal"), False, zero.reason, t("cal_fix")))
        return stages
    if io.ask(t("cal_ask")).strip().lower() in NO_ANSWERS:  # the only question: a look at the hand
        ctrl.link.zero_rad = old_zero  # do not keep a zero found at a stop that is not the closed position
        record(Stage(t("st_cal"), False, t("cal_not_closed"), t("cal_fix")))
        return stages
    if not record(Stage(t("st_cal"), abs(q - lim.expected_closed_rad) <= lim.calibration_tolerance_rad,
                        t("cal_detail", q=q, exp=lim.expected_closed_rad, tol=lim.calibration_tolerance_rad)
                        + t("cal_auto", travel=zero.travel_rad), t("cal_fix"))):
        return stages
    out = ctrl.move_to(SMALL_MOVE_RAD)
    back = ctrl.move_to(lim.closed_target_rad) if out.ok else out
    moved = out.ok and back.ok and out.peak_rad >= SMALL_MOVE_RAD - 0.15 and abs(back.end_rad - lim.closed_target_rad) < 0.3
    detail = t("motion_detail", p=out.peak_rad, b=back.end_rad) + ("" if out.ok and back.ok else t("motion_stopped", r=out.reason or back.reason))
    record(Stage(t("st_motion"), moved, detail, t("motion_fix")))
    return stages
