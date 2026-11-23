"""A simulated hand for tests and for trying the tools without hardware.

It decodes control frames, moves toward the commanded angle (first-order lag) and answers like a real hand.
Faults can be injected: drop replies, over-temperature, MError, or a stuck finger.
"""
from __future__ import annotations

import math
import struct
from collections.abc import Callable

from .protocol import (CONTROL_LEN, GEAR_RATIO, HEAD_CONTROL, ROTOR_COUNTS_PER_REV, STATUS_FOC, build_reply,
                       crc32_core)
from .transport import Exchange, Transport

LAG_PER_EXCHANGE = 0.3  # fraction of the remaining distance covered per control frame


class MockHand(Transport):
    def __init__(self, motor_id: int = 7, q: float = -0.007, max_q: float = 5.35) -> None:
        self.motor_id, self.q, self.max_q = motor_id, q, max_q
        self.temp, self.volts, self.merror = 30, 24.0, 0
        self.drop_replies = 0  # the next N frames get no reply
        self.silent_after = None  # int: no reply to any frame once this many frames have been received
        self.stuck = False  # the hand does not move
        self.sent: list[bytes] = []  # every frame received, for assertions
        self.closed = False

    def exchange(self, frame: bytes, wait_s: float, done: Callable[[bytes], bool]) -> Exchange:
        self.sent.append(frame)
        if len(frame) != CONTROL_LEN or frame[:2] != HEAD_CONTROL or struct.unpack("<I", frame[16:])[0] != crc32_core(frame[:16]):
            return Exchange(b"", 0.0, None)
        mode = frame[2]
        _, _, tor, spd, pos, k_pos, _ = struct.unpack("<BBhhiHH", frame[2:16])
        if (mode & 0xF) != self.motor_id:
            return Exchange(b"", 0.0, None)
        if (mode >> 4) & 0x7 == STATUS_FOC and k_pos > 0 and not self.stuck:
            target = pos / ROTOR_COUNTS_PER_REV * 2 * math.pi / GEAR_RATIO
            self.q = min(max(self.q + (target - self.q) * LAG_PER_EXCHANGE, -0.06), self.max_q)
        if self.silent_after is not None and len(self.sent) > self.silent_after:
            return Exchange(b"", 0.0, None)
        if self.drop_replies > 0:
            self.drop_replies -= 1
            return Exchange(b"", 0.0, None)
        return Exchange(build_reply(self.motor_id, self.q, self.temp, self.temp, self.volts, self.merror), 0.0, 7e-6)

    def close(self) -> None:
        self.closed = True
