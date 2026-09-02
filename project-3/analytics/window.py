"""Klizni prozor očitavanja po uređaju + throttling poziva ka MLaaS-u."""

from __future__ import annotations

import time
from collections import deque


class DeviceWindows:
    """Održava po jedan klizni prozor za svaki uređaj.

    `should_predict` ograničava učestalost poziva ka MLaaS-u: pri replay-u od
    200 poruka/s bez toga bi Analytics slao stotine HTTP zahteva u sekundi.
    """

    def __init__(self, size: int, predict_interval: float) -> None:
        self.size = size
        self.predict_interval = predict_interval
        self._windows: dict[str, deque] = {}
        self._last_predict: dict[str, float] = {}

    def add(self, device_id: str, reading: dict) -> deque:
        win = self._windows.setdefault(device_id, deque(maxlen=self.size))
        win.append(reading)
        return win

    def is_full(self, device_id: str) -> bool:
        win = self._windows.get(device_id)
        return win is not None and len(win) == self.size

    def should_predict(self, device_id: str, now: float | None = None) -> bool:
        if not self.is_full(device_id):
            return False
        now = time.monotonic() if now is None else now
        last = self._last_predict.get(device_id)
        if last is not None and (now - last) < self.predict_interval:
            return False
        self._last_predict[device_id] = now
        return True

    def snapshot(self, device_id: str) -> list[dict]:
        return list(self._windows.get(device_id, []))

    @property
    def devices(self) -> list[str]:
        return list(self._windows)
