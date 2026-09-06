"""Runtime port consumed by application services; contains no Codex SDK types."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.events.models import AgentEvent


class AgentRuntime(Protocol):
    async def create_thread(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> str: ...

    async def archive_thread(self, thread_id: str) -> None: ...

    async def read_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]: ...

    async def compact_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> None: ...

    async def run_turn(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> str: ...

    def stream_turn(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> AsyncIterator[AgentEvent]: ...
