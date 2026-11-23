"""Settings: hand, safety limits and transport. Defaults are measured on one right hand (motor id 7); see docs/safety.md.

Load from TOML with load_config(); unknown keys raise ValueError (fail fast, no silent typos).
"""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from .protocol import DEFAULT_KD_RAW, DEFAULT_KP_RAW


@dataclass(frozen=True)
class HandConfig:
    motor_id: int = 7
    kp_raw: int = DEFAULT_KP_RAW
    kd_raw: int = DEFAULT_KD_RAW


@dataclass(frozen=True)
class Limits:
    """Every motion is checked against these. Angles are output-axis radians after calibration."""
    position_min_rad: float = -0.2  # lowest target accepted (closed stop is about -0.06)
    open_limit_rad: float = 5.2  # highest target accepted (the open stop is about 5.35)
    start_slack_rad: float = 0.5  # the hand may start this far outside min..max before we refuse to move
    closed_target_rad: float = 0.1  # "closed" as a target: a little off the stop, so it does not push on it
    open_target_rad: float = 5.1  # "open" as a target
    expected_closed_rad: float = -0.007  # what a fully hand-closed, calibrated hand reads
    calibration_tolerance_rad: float = 0.2
    max_track_err_rad: float = 0.6  # abort when the measured angle is this far from the commanded one
    max_temp_c: int = 60
    max_missed_replies: int = 3  # consecutive
    max_speed_rad_s: float = 1.5  # peak speed of the cosine ramp; longer ramps are forced when needed
    min_ramp_s: float = 1.0
    default_ramp_s: float = 5.0
    max_ramp_s: float = 120.0  # longest accepted request (inf, nan and absurd values are rejected)
    step_s: float = 0.04
    brake_repeats: int = 3
    min_strength_pct: float = 10.0  # position gain as a share of hand.kp_raw; the default is the highest accepted
    max_strength_pct: float = 100.0
    zero_speed_rad_s: float = 0.4  # auto zero: closing speed (a choice, not measured on the hand)
    zero_lead_rad: float = 0.15  # auto zero: how far ahead of the finger the target may be, so the push on the stop stays bounded
    zero_kp_raw: int = 50  # auto zero: gain, about half the default (a choice, not measured)
    zero_stall_s: float = 0.6  # auto zero: the finger counts as stopped when it moved less than zero_stall_move_rad for this long
    zero_stall_move_rad: float = 0.01
    zero_tolerance_rad: float = 0.5  # auto zero: refuse a stop this far from expected_closed_rad when the hand started in range

    def __post_init__(self) -> None:
        for name in ("max_speed_rad_s", "min_ramp_s", "step_s", "default_ramp_s", "max_ramp_s", "zero_speed_rad_s", "zero_lead_rad",
                     "zero_stall_s", "zero_stall_move_rad", "zero_tolerance_rad", "min_strength_pct"):
            if getattr(self, name) <= 0:
                raise ValueError(f"limits.{name} must be > 0")
        if not self.position_min_rad < self.closed_target_rad < self.open_target_rad <= self.open_limit_rad:
            raise ValueError("limits need position_min < closed_target < open_target <= open_limit")
        if not self.min_ramp_s <= self.default_ramp_s <= self.max_ramp_s:
            raise ValueError("limits need min_ramp_s <= default_ramp_s <= max_ramp_s")
        if not (math.isfinite(self.max_track_err_rad) and self.max_track_err_rad > 0):
            raise ValueError("limits.max_track_err_rad must be a positive number")
        if not 0 < self.min_strength_pct <= self.max_strength_pct or self.zero_kp_raw < 1:
            raise ValueError("limits need 0 < min_strength_pct <= max_strength_pct and zero_kp_raw >= 1")

    def check_strength(self, pct: float) -> float:
        """A requested strength in percent of hand.kp_raw, or ValueError when it is outside min..max_strength_pct."""
        if not (math.isfinite(pct) and self.min_strength_pct <= pct <= self.max_strength_pct):
            raise ValueError(f"strength must be {self.min_strength_pct:g}..{self.max_strength_pct:g} %, got {pct}")
        return pct

    def check_speed(self, speed_rad_s: float) -> float:
        """A requested peak speed [rad/s], or ValueError when it is not within (0, max_speed_rad_s]."""
        if not (math.isfinite(speed_rad_s) and 0 < speed_rad_s <= self.max_speed_rad_s):
            raise ValueError(f"speed must be a number in (0, {self.max_speed_rad_s:g}] rad/s, got {speed_rad_s}")
        return speed_rad_s

    def check_ramp(self, ramp_s: float) -> float:
        """A requested ramp time, or ValueError when it is not a finite number within (0, max_ramp_s]."""
        if not (math.isfinite(ramp_s) and 0 < ramp_s <= self.max_ramp_s):
            raise ValueError(f"ramp must be a number in (0, {self.max_ramp_s:g}] seconds, got {ramp_s}")
        return ramp_s


@dataclass(frozen=True)
class TransportConfig:
    kind: str = "espprog"  # "espprog" or "mock"
    port_b: str = "auto"  # ESP-Prog channel B (UART receive side): "auto" finds it, or a path such as /dev/ttyUSB1
    ftdi_url: str = "ftdi://ftdi:2232h/1"  # ESP-Prog channel A, bit-banged transmit + direction
    baud: int = 6_000_000
    reply_wait_s: float = 0.05


@dataclass(frozen=True)
class Config:
    hand: HandConfig = field(default_factory=HandConfig)
    limits: Limits = field(default_factory=Limits)
    transport: TransportConfig = field(default_factory=TransportConfig)
    log_dir: str = "~/.local/share/dex1-rs485/logs"
    lang: str = "auto"  # messages: "auto" (from the locale), "en" or "ja"


def _build(cls, table: dict, where: str):
    known = {f.name for f in fields(cls)}
    extra = set(table) - known
    if extra:
        raise ValueError(f"unknown key(s) in [{where}]: {', '.join(sorted(extra))}")
    return cls(**table)


def load_config(path: str | Path | None) -> Config:
    """Defaults when path is None; otherwise the TOML file overrides them section by section."""
    if path is None:
        return Config()
    data = tomllib.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    extra = set(data) - {"hand", "limits", "transport", "log_dir", "lang"}
    if extra:
        raise ValueError(f"unknown top-level key(s): {', '.join(sorted(extra))}")
    cfg = Config()
    return replace(
        cfg,
        hand=_build(HandConfig, data.get("hand", {}), "hand"),
        limits=_build(Limits, data.get("limits", {}), "limits"),
        transport=_build(TransportConfig, data.get("transport", {}), "transport"),
        log_dir=data.get("log_dir", cfg.log_dir),
        lang=data.get("lang", cfg.lang),
    )
