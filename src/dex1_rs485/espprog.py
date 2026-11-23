"""ESP-Prog (FT2232H) + MAX3485 transport. See docs/wiring.md.

Channel A (JTAG connector) is bit-banged with pyftdi's synchronous GPIO: one sample = one UART bit at the baud rate.
TDI carries the transmit data, TMS the driver-enable (EN), so the chip clocks both out together. Switching EN over USB
would take about 1 ms, but the hand answers about 7 us after the query ends.
Channel B (Program connector) is an ordinary UART used receive-only, with DTR and RTS held Low.
"""
from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable

from .config import TransportConfig
from .i18n import t
from .transport import Exchange, Transport

PIN_TDI = 0x02  # ADBUS1 (JTAG pin 8) -> MAX3485 board's RXD terminal (the driver input)
PIN_TMS = 0x08  # ADBUS3 (JTAG pin 2) -> MAX3485 board's EN
DIRECTION = PIN_TDI | PIN_TMS
IDLE_SAMPLES = 8
EN_LEAD_BITS = 1  # EN rises this many bits before the start bit
EN_TAIL_BITS = 1  # EN falls this many bits after the stop bit
HOLDER_PATTERN = "dex1_1_gripper_server|dds_gripper"  # vendor processes that own the same serial ports


def uart_bits(data: bytes) -> list[int]:
    """8N1, LSB first, one TXD level per bit."""
    bits: list[int] = []
    for byte in data:
        bits.append(0)
        bits.extend((byte >> i) & 1 for i in range(8))
        bits.append(1)
    return bits


def build_samples(frame: bytes, en_tail_bits: int = EN_TAIL_BITS) -> bytes:
    """One byte per sample: TXD on PIN_TDI, EN on PIN_TMS."""
    def sample(txd: int, en: int) -> int:
        return (PIN_TDI if txd else 0) | (PIN_TMS if en else 0)

    return bytes([sample(1, 0)] * IDLE_SAMPLES + [sample(1, 1)] * EN_LEAD_BITS
                 + [sample(b, 1) for b in uart_bits(frame)] + [sample(1, 1)] * en_tail_bits
                 + [sample(1, 0)] * IDLE_SAMPLES)


ESP_PROG_VID, ESP_PROG_PID = 0x0403, 0x6010
PORT_AUTO = "auto"


def find_channel_b() -> str:
    """Find the ESP-Prog UART port (channel B) on Linux and macOS.

    pyftdi detaches channel A from the OS driver, so after it is opened only channel B is left with this VID/PID.
    If both are listed, prefer the interface-1 one (Linux location '...:1.1', macOS name ending in B or 1).
    """
    from serial.tools import list_ports

    found = sorted((p for p in list_ports.comports() if (p.vid, p.pid) == (ESP_PROG_VID, ESP_PROG_PID)),
                   key=lambda p: p.device)
    if not found:
        raise RuntimeError("no ESP-Prog (0403:6010) serial port found; plug it in, or set transport.port_b")
    if len(found) == 1:
        return found[0].device
    for p in found:
        if (p.location or "").endswith(".1") or p.device.endswith(("B", "1")):
            return p.device
    return found[-1].device


class EspProgTransport(Transport):
    warmup_exchanges = 1

    def __init__(self, cfg: TransportConfig) -> None:
        try:
            import serial
            from pyftdi.gpio import GpioSyncController
        except ImportError as e:
            raise RuntimeError("the espprog transport needs pyftdi and pyserial: pip install 'dex1-rs485[espprog]'") from e
        self.cfg = cfg
        self._gpio = GpioSyncController()
        self._gpio.configure(cfg.ftdi_url, direction=DIRECTION, frequency=cfg.baud, initial=PIN_TDI)
        if round(self._gpio.frequency) != cfg.baud:
            self._gpio.close()
            raise RuntimeError(f"FTDI sample clock {self._gpio.frequency:.0f} Hz != baud {cfg.baud}; the bit timing would be wrong")
        # DTR/RTS must stay Low: asserting DTR makes the replies stop after about 1 s (measured; cause unconfirmed).
        self._ser = serial.Serial(None, cfg.baud, timeout=0)
        self._ser.dtr = self._ser.rts = False
        self._ser.port = find_channel_b() if cfg.port_b == PORT_AUTO else cfg.port_b
        self._ser.open()
        self._ser.dtr = self._ser.rts = False

    def exchange(self, frame: bytes, wait_s: float, done: Callable[[bytes], bool]) -> Exchange:
        self._ser.read(4096)  # drop stale bytes (reset_input_buffer() per frame froze reception after ~1 s)
        t_tx = time.monotonic()
        self._gpio.exchange(build_samples(frame))
        t_sent = time.monotonic()
        buf, t_first = b"", None
        end = t_sent + wait_s
        while time.monotonic() < end and not done(buf):
            chunk = self._ser.read(4096)
            if chunk and t_first is None:
                t_first = time.monotonic()
            buf += chunk
        return Exchange(buf, t_sent - t_tx, None if t_first is None else t_first - t_sent)

    def close(self) -> None:
        self._ser.close()
        self._gpio.close()

    def check_environment(self) -> tuple[bool, str, str]:
        port = find_channel_b() if self.cfg.port_b == PORT_AUTO else self.cfg.port_b
        ports = [port] if os.path.exists(port) else []
        out = subprocess.run(["pgrep", "-af", HOLDER_PATTERN], capture_output=True, text=True).stdout
        holders = [line for line in out.splitlines() if "pgrep" not in line]
        ok = bool(ports) and not holders
        return (ok, t("env_detail", ports=ports or t("env_missing"), holders=holders or t("env_none")), t("env_fix"))
