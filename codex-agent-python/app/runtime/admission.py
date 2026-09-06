"""Single-event-loop admission control, independent of Codex and business tools.

A lease is owned by the execution task, not by its HTTP consumer. Client disconnects
must not unlock a conversation while a remote operation is still running.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class AdmissionRejected(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ExecutionFailed(RuntimeError):
    """The runtime confirmed a terminal failure; safe to release its admission slot."""


class RuntimeUnavailable(RuntimeError):
    """Remote completion could not be confirmed; admission is closed."""


class AdmissionController:
    """Fail-fast, bounded concurrency; deploy with exactly one process/runtime.

    There is deliberately no unbounded waiting queue. Unknown execution failures close
    admission until reconciliation/restart: releasing a Python task does not prove the
    remote operation stopped. Never share this controller across event loops.
    """

    def __init__(self, max_active: int, operation_timeout_seconds: float = 180.0) -> None:
        if max_active < 1 or operation_timeout_seconds <= 0:
            raise ValueError("max_active must be positive")
        self._limit = max_active
        self._operation_timeout = operation_timeout_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        self._accepting = True

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def submit(self, key: str, operation: Callable[[], Awaitable[T]]) -> asyncio.Task[T]:
        # No await between admission checks and reservation: atomic on one event loop.
        if not self._accepting:
            raise AdmissionRejected("SERVICE_UNAVAILABLE", 503)
        if key in self._tasks:
            raise AdmissionRejected("CONVERSATION_BUSY", 409)
        if len(self._tasks) >= self._limit:
            raise AdmissionRejected("CAPACITY_EXCEEDED", 503)

        async def execute() -> T:
            try:
                async with asyncio.timeout(self._operation_timeout):
                    return await operation()
            except ExecutionFailed:
                raise
            except asyncio.CancelledError:
                self._accepting = False
                raise
            except Exception:
                # Transport failure/cancellation may leave a live remote Turn.
                self._accepting = False
                raise RuntimeUnavailable("RUNTIME_OUTCOME_UNKNOWN") from None
            finally:
                self._tasks.pop(key, None)

        task = asyncio.create_task(execute())
        self._tasks[key] = task
        # Retrieve detached exceptions without printing potentially sensitive payloads.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return task

    async def run(self, key: str, operation: Callable[[], Awaitable[T]]) -> T:
        return await asyncio.shield(self.submit(key, operation))

    async def drain(self, timeout_seconds: float) -> bool:
        self._accepting = False
        pending = list(self._tasks.values())
        if not pending:
            return True
        _, remaining = await asyncio.wait(pending, timeout=timeout_seconds)
        return not remaining

    async def cancel_after_runtime_closed(self) -> None:
        """Only call after stopping the remote runtime, never on HTTP disconnect."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
