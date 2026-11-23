"""Transport interface: send one frame, collect what comes back. Implementations: espprog.py (hardware), mock.py (tests)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Exchange:
    raw: bytes  # everything received after the frame
    tx_s: float  # time spent sending
    first_rx_s: float | None  # first received byte, measured from the end of sending


class Transport(ABC):
    warmup_exchanges = 0  # exchanges to send and discard after opening (the ESP-Prog loses the first one)

    @abstractmethod
    def exchange(self, frame: bytes, wait_s: float, done: Callable[[bytes], bool]) -> Exchange:
        """Send frame, then collect bytes until done(received) is true or wait_s passes."""

    @abstractmethod
    def close(self) -> None: ...

    def check_environment(self) -> tuple[bool, str, str]:
        """(ok, detail, how to fix) for the preflight's first stage."""
        return True, "n/a", ""
