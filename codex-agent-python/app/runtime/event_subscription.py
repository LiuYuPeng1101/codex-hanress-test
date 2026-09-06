"""A bounded event subscriber; slow/disconnected clients do not own execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.events.models import AgentEvent


class EventSubscription:
    def __init__(self, conversation_id: str, max_events: int = 128) -> None:
        self._conversation_id = conversation_id
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=max_events)
        self._changed = asyncio.Event()
        self._detached = False
        self._finished = False
        self._error: str | None = None

    def publish(self, event: AgentEvent) -> None:
        if self._detached:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._error = "STREAM_CONSUMER_TOO_SLOW"
            self.aclose()
        self._changed.set()

    def finish(self, error: str | None = None) -> None:
        self._finished = True
        self._error = self._error or error
        self._changed.set()

    def aclose(self) -> None:
        self._detached = True
        while not self._queue.empty():
            self._queue.get_nowait()
        self._changed.set()

    async def events(self) -> AsyncIterator[AgentEvent]:
        try:
            while True:
                if self._error:
                    yield AgentEvent("error", self._conversation_id, {"code": self._error})
                    return
                if not self._queue.empty():
                    yield self._queue.get_nowait()
                    continue
                if self._finished or self._detached:
                    return
                self._changed.clear()
                await self._changed.wait()
        finally:
            self.aclose()
