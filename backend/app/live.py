"""Live updates: every ingested event is broadcast to connected WebSocket clients (bounded per-client queues)."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Set


class Broadcaster:
    def __init__(self, per_client: int = 100):
        self.clients: Set[asyncio.Queue] = set()
        self.per_client = per_client

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.per_client)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def publish(self, msg: Dict[str, Any]) -> None:
        for q in list(self.clients):
            if q.full():  # slow client: drop its oldest message
                q.get_nowait()
            q.put_nowait(msg)


broadcaster = Broadcaster()
