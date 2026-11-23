"""Prompter for the browser: say() becomes a log line, ask() becomes a dialog and waits for the person's answer."""
from __future__ import annotations

import itertools
import threading

from ..i18n import t
from .events import EventBus

ANSWER_TIMEOUT_S = 600.0


class WebPrompter:
    def __init__(self, bus: EventBus, timeout_s: float = ANSWER_TIMEOUT_S) -> None:
        self.bus, self.timeout_s = bus, timeout_s
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, list[str | None]]] = {}

    def say(self, msg: str) -> None:
        self.bus.publish("msg", text=msg)

    def ask(self, prompt: str) -> str:
        """Blocks until answer() or abort(). Raises EOFError when aborted or after the timeout (nothing is assumed)."""
        qid, done, box = next(self._ids), threading.Event(), [None]
        with self._lock:
            self._pending[qid] = (done, box)
        topic = "calibration" if prompt == t("cal_ask") else ""  # the page explains this question in its own words
        self.bus.publish("ask", qid=qid, text=prompt.strip(), choices=["yes", "no"], topic=topic)
        done.wait(self.timeout_s)
        with self._lock:
            self._pending.pop(qid, None)
        self.bus.publish("ask_done", qid=qid)
        if box[0] is None:
            raise EOFError
        return box[0]

    def answer(self, qid: int, value: str) -> bool:
        with self._lock:
            entry = self._pending.get(qid)
        if entry is None:
            return False
        entry[1][0] = "n" if value == "no" else ""  # "n" is what the terminal flow treats as a refusal; Enter is ""
        entry[0].set()
        return True

    def abort(self) -> None:
        with self._lock:
            entries = list(self._pending.values())
        for done, _ in entries:
            done.set()  # box stays None -> EOFError in ask()
