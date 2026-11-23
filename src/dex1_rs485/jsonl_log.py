"""One JSON object per line: every exchange with timings, raw bytes and every field of the reply."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol

from .protocol import Reply


class Log(Protocol):
    path: str

    def write(self, kind: str, trace: dict, reply: Reply | None, **extra: object) -> None: ...
    def close(self) -> None: ...


class NullLog:
    path = ""

    def write(self, kind: str, trace: dict, reply: Reply | None, **extra: object) -> None:
        pass

    def close(self) -> None:
        pass


class JsonlLog:
    def __init__(self, log_dir: str, prefix: str, header: dict | None = None) -> None:
        directory = Path(os.path.expanduser(log_dir))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = str(directory / time.strftime(f"{prefix}-%Y%m%d-%H%M%S.jsonl"))
        self._f = open(self.path, "w", encoding="utf-8")
        self._t0 = time.monotonic()
        if header is not None:
            self._f.write(json.dumps({"kind": "header", "started": time.strftime("%F %T"), **header}) + "\n")

    def write(self, kind: str, trace: dict, reply: Reply | None, **extra: object) -> None:
        row = {"t": round(time.monotonic() - self._t0, 3), "kind": kind, **extra, **trace}
        if reply is not None:
            row.update(status=reply.status, timeout=reply.timeout, temp_case=reply.temp_case, temp_coil=reply.temp_coil,
                       volts=reply.volts, torque_raw=reply.torque_raw, speed_raw=reply.speed_raw, pos_raw=reply.pos_raw,
                       q_out=round(reply.output_rad, 4), merror=reply.merror, crc=list(reply.crc_variants))
        self._f.write(json.dumps(row) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()
