"""One background dependency probe; readiness requests never queue database work."""

import asyncio
from collections.abc import Callable
from time import monotonic

from starlette.concurrency import run_in_threadpool


class DependencyReadiness:
    def __init__(
        self, probes: tuple[Callable[[], None], ...], interval: float = 5, max_age: float = 20
    ):
        self._probes = probes
        self._interval = interval
        self._max_age = max_age
        self._last_success: float | None = None
        self._healthy = False
        self._task: asyncio.Task | None = None

    @property
    def ready(self) -> bool:
        return (
            self._healthy
            and self._last_success is not None
            and monotonic() - self._last_success < self._max_age
        )

    async def check(self) -> None:
        try:
            for probe in self._probes:
                await run_in_threadpool(probe)
        except Exception:
            self._healthy = False
        else:
            self._last_success = monotonic()
            self._healthy = True

    async def start(self) -> None:
        await self.check()
        if not self.ready:
            raise RuntimeError("DATABASE_NOT_READY")
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            await asyncio.sleep(self._interval)
            await self.check()

    async def close(self) -> None:
        self._healthy = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
