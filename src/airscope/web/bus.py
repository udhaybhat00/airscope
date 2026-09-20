"""Tiny pub/sub hub: the engine publishes, every WebSocket gets a copy."""
from __future__ import annotations

import asyncio


class Bus:
    """One queue per subscriber; slow readers never block the engine."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """A fresh queue receiving every future event."""
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, topic: str, payload: dict) -> None:
        """Drop one event to all subscribers (full queues shed oldest)."""
        for q in list(self._queues):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait({"topic": topic, "payload": payload})
            except asyncio.QueueFull:
                pass
