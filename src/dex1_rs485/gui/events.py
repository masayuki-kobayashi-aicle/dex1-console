"""A small publish/subscribe bus. Every event is kept in a bounded history so a browser that connects late (or
reconnects) sees what already happened."""
from __future__ import annotations

import queue
import threading
import time
from collections import deque

HISTORY = 1000


class EventBus:
    def __init__(self, history: int = HISTORY) -> None:
        self._lock = threading.Lock()
        self._history: deque[dict] = deque(maxlen=history)
        self._subscribers: list[queue.Queue] = []
        self._next_id = 1
        self._t0 = time.monotonic()

    def publish(self, type_: str, **data: object) -> dict:
        with self._lock:
            event = {"id": self._next_id, "type": type_, "t": round(time.monotonic() - self._t0, 3), "at": round(time.time(), 3), **data}
            self._next_id += 1
            self._history.append(event)
            for q in self._subscribers:
                q.put(event)
        return event

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        """The history so far and a queue of everything after it (no event is missed or repeated)."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            past = list(self._history)
            self._subscribers.append(q)
        return past, q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
