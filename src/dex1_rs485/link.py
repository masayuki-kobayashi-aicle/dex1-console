"""One hand on one transport: send a frame, parse the reply, log the exchange."""
from __future__ import annotations

from dataclasses import replace

from .jsonl_log import Log, NullLog
from .protocol import Reply, build_idle, find_reply
from .transport import Transport


class LinkError(RuntimeError):
    """The hand did not answer when it had to (wiring, power, or a stale transport)."""


class Link:
    def __init__(self, transport: Transport, motor_id: int, reply_wait_s: float = 0.05, log: Log | None = None) -> None:
        self.transport, self.motor_id, self.reply_wait_s = transport, motor_id, reply_wait_s
        self.log: Log = log or NullLog()
        self.zero_rad = 0.0  # set by calibrate.auto_zero; replies carry it, commands add it back (Controller)
        self.last_raw = b""
        self.last_first_rx_ms: float | None = None  # first byte after the end of sending, host-side, of the last exchange
        for _ in range(transport.warmup_exchanges):
            self.transport.exchange(build_idle(motor_id), reply_wait_s, lambda buf: False)

    def txrx(self, frame: bytes, kind: str = "txrx", **extra: object) -> Reply | None:
        """Send frame, return the reply or None. The exchange is logged either way."""
        reply: Reply | None = None

        def done(buf: bytes) -> bool:
            nonlocal reply
            reply, _ = find_reply(buf)
            return reply is not None

        ex = self.transport.exchange(frame, self.reply_wait_s, done)
        self.last_raw = ex.raw
        self.last_first_rx_ms = None if ex.first_rx_s is None else ex.first_rx_s * 1000
        if reply is None:
            reply, _ = find_reply(ex.raw)
        if reply is not None and self.zero_rad:
            reply = replace(reply, zero_rad=self.zero_rad)
        trace = {"tx": frame.hex(" "), "tx_ms": round(ex.tx_s * 1000, 2),
                 "first_rx_ms": None if ex.first_rx_s is None else round(ex.first_rx_s * 1000, 2),
                 "rx_len": len(ex.raw), "rx": ex.raw.hex(" ")}
        self.log.write(kind, trace, reply, **extra)
        return reply

    def close(self) -> None:
        self.log.close()
        self.transport.close()
