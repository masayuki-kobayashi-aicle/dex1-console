"""Dex1-1 (M4010) RS-485 frames and unit conversion. Pure Python, no hardware dependencies.

Layout (from Unitree's public header motor_msg_HG.h, and verified against frames produced by the vendor SDK):
  control, 20 B: head fe ee | id | status<<4 | timeout<<7 | reserved | tor_des i16 | spd_des i16 | pos_des i32
                 | k_pos u16 | k_spd u16 | CRC32
  reply,   26 B: head fc ee | id | status<<4 | timeout<<7 | temp_case i8 | temp_coil u8 | volts*2 u8 | torque i16
                 | speed i16 | pos i32 | MError u32 | ExData 4 B | CRC32
CRC32 is the vendor's `crc32_core` (poly 0x04c11db7, init 0xFFFFFFFF, little-endian 32-bit words).
Which byte range the reply CRC covers is not documented; REPLY_CRC_VARIANTS lists the candidates and a Reply
reports which ones matched.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

CONTROL_LEN = 20
REPLY_LEN = 26
HEAD_CONTROL = b"\xfe\xee"
HEAD_REPLY = b"\xfc\xee"
STATUS_LOCK = 0  # brake
STATUS_FOC = 1  # position / torque control
MOTOR_ID_MAX = 15
QUERY_SPD_DES_RAW = 0x53A1  # raw value the vendor server puts in its discovery query; meaning unknown, copied verbatim
ROTOR_COUNTS_PER_REV = 32768
GEAR_RATIO = 25.0  # M4010 as used in the Dex1-1
REPLY_CRC_VARIANTS = ("A", "B", "C")  # A: bytes 2..21, B: bytes 0..19, C: bytes 0..21 + 2 zero bytes
DEFAULT_KP_RAW = 102  # vendor kp 5 (output side) -> raw. Measured by calling the vendor library, nothing sent.
DEFAULT_KD_RAW = 1  # vendor kd 0.05 -> raw (the scale is coarse)


def crc32_core(data: bytes) -> int:
    if len(data) % 4:
        raise ValueError(f"crc32_core needs a multiple of 4 bytes, got {len(data)}")
    crc = 0xFFFFFFFF
    for (word,) in struct.iter_unpack("<I", data):
        crc ^= word
        for _ in range(32):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def build_control(motor_id: int, status: int, timeout: int, tor_des: int, spd_des: int,
                  pos_des: int, k_pos: int, k_spd: int) -> bytes:
    """Raw-value control frame. Out-of-range input raises ValueError (never silently clamped)."""
    if not 0 <= motor_id <= MOTOR_ID_MAX:
        raise ValueError(f"motor_id {motor_id} not in 0..{MOTOR_ID_MAX}")
    if status not in (STATUS_LOCK, STATUS_FOC):
        raise ValueError(f"status {status} must be 0 (lock) or 1 (FOC)")
    mode = (motor_id & 0xF) | (status << 4) | ((timeout & 1) << 7)
    body = HEAD_CONTROL + struct.pack("<BBhhiHH", mode, 0, tor_des, spd_des, pos_des, k_pos, k_spd)
    return body + struct.pack("<I", crc32_core(body))


def build_query(motor_id: int) -> bytes:
    """State query (does not move the hand); same bytes as the vendor server's discovery frame."""
    return build_control(motor_id, STATUS_FOC, 0, 0, QUERY_SPD_DES_RAW, 0, 0, 0)


def build_lock(motor_id: int) -> bytes:
    """Brake: status 0, every raw value 0. Sent on abort and on exit."""
    return build_control(motor_id, STATUS_LOCK, 0, 0, 0, 0, 0, 0)


def build_idle(motor_id: int) -> bytes:
    """FOC with zero gains: reads the state without applying torque (the hand can be moved by hand)."""
    return build_control(motor_id, STATUS_FOC, 0, 0, 0, 0, 0, 0)


def pos_raw(q_out_rad: float) -> int:
    """Output-axis angle [rad] -> raw pos_des (rotor counts), truncated toward zero like the vendor library."""
    return int(q_out_rad * GEAR_RATIO * ROTOR_COUNTS_PER_REV / (2 * math.pi))


def build_position(motor_id: int, q_out_rad: float, kp_raw: int = DEFAULT_KP_RAW, kd_raw: int = DEFAULT_KD_RAW) -> bytes:
    """Position command for the output axis [rad]."""
    return build_control(motor_id, STATUS_FOC, 0, 0, 0, pos_raw(q_out_rad), kp_raw, kd_raw)


@dataclass(frozen=True)
class Reply:
    motor_id: int
    status: int
    timeout: int
    temp_case: int
    temp_coil: int
    volts: float
    torque_raw: int
    speed_raw: int
    pos_raw: int
    merror: int
    crc_variants: tuple[str, ...]
    zero_rad: float = 0.0  # software zero (calibrate.auto_zero); the hand's own calibration is not touched

    @property
    def raw_rad(self) -> float:
        """Output-axis angle [rad] in the hand's own calibration (rotor angle divided by the gear ratio)."""
        return self.pos_raw / ROTOR_COUNTS_PER_REV * 2 * math.pi / GEAR_RATIO

    @property
    def output_rad(self) -> float:
        """Output-axis angle [rad] relative to the software zero (equal to raw_rad until auto_zero has run)."""
        return self.raw_rad - self.zero_rad


def reply_crc(frame: bytes, variant: str) -> int:
    if variant == "A":
        return crc32_core(frame[2:22])
    if variant == "B":
        return crc32_core(frame[0:20])
    if variant == "C":
        return crc32_core(frame[0:22] + b"\0\0")
    raise ValueError(f"unknown CRC variant {variant!r}")


def build_reply(motor_id: int, q_out_rad: float, temp_case: int = 30, temp_coil: int = 30, volts: float = 24.0,
                merror: int = 0, torque_raw: int = 0, speed_raw: int = 0, variant: str = "A") -> bytes:
    """A reply frame as a hand would send it. Used by the mock hand and the tests."""
    body = struct.pack("<2sBbBBhhiI4s", HEAD_REPLY, (motor_id & 0xF) | (STATUS_FOC << 4), temp_case, temp_coil,
                       int(volts * 2), torque_raw, speed_raw, pos_raw(q_out_rad), merror, b"\0" * 4)
    return body + struct.pack("<I", reply_crc(body + b"\0\0\0\0", variant))


def find_reply(buf: bytes) -> tuple[Reply | None, int]:
    """Find one valid reply in buf. Returns (reply or None, bytes consumed). Corrupt frames are skipped."""
    start = 0
    while True:
        at = buf.find(HEAD_REPLY, start)
        if at < 0:
            return None, max(0, len(buf) - 1)  # the last byte may be half of a head
        if len(buf) - at < REPLY_LEN:
            return None, at
        frame = buf[at:at + REPLY_LEN]
        want = struct.unpack("<I", frame[22:])[0]
        fits = tuple(v for v in REPLY_CRC_VARIANTS if reply_crc(frame, v) == want)
        if fits:
            return _decode(frame, fits), at + REPLY_LEN
        start = at + 1


def _decode(frame: bytes, fits: tuple[str, ...]) -> Reply:
    _, mode, temp1, temp2, vol, torque, speed, pos, merr = struct.unpack("<2sBbBBhhiI", frame[:18])
    return Reply(mode & 0xF, (mode >> 4) & 0x7, mode >> 7, temp1, temp2, vol / 2, torque, speed, pos, merr, fits)
