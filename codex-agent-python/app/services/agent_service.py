from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any

from app.conversations.conversation_repository import Conversation, ConversationRepository
from app.events.models import AgentEvent
from app.runtime.codex_runtime import CodexRuntime


class RuntimeLeaseConflict(RuntimeError):
    """Conversation 当前仍由其他健康 Runtime Worker 持有 lease。"""

    def __init__(self, owner: str, expires_at: datetime) -> None:
        super().__init__(f"Conversation 当前由 Runtime Worker {owner} 持有 lease")
        self.owner = owner
        self.expires_at = expires_at


class RuntimeLeaseLost(RuntimeError):
    """当前 Worker 在执行过程中失去了 Conversation lease。"""


class AgentService:
    """企业 Agent 应用服务。

    外部只处理 business conversation_id。每次执行前原子获取 lease，执行期间持续 heartbeat；
    Worker 实例不是永久归属。实际故障接管仍依赖可恢复的 CODEX_HOME / Runtime Storage。
    """

    def __init__(
        self,
        runtime: CodexRuntime,
        conversations: ConversationRepository,
        *,
        agent_id: str,
        runtime_instance_id: str,
        runtime_lease_seconds: int,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self._agent_id = agent_id
        self._runtime_instance_id = runtime_instance_id
        self._runtime_lease_seconds = runtime_lease_seconds
        self._heartbeat_interval_seconds = max(1.0, runtime_lease_seconds / 3)

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> Conversation:
        conversation_id = self._conversations.new_id()
        runtime_thread_id = await self._runtime.create_thread(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        try:
            return await asyncio.to_thread(
                self._conversations.create,
                conversation_id=conversation_id,
                agent_id=self._agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                runtime_type="codex",
                runtime_thread_id=runtime_thread_id,
                runtime_instance_id=self._runtime_instance_id,
                lease_seconds=self._runtime_lease_seconds,
            )
        except Exception:
            try:
                await self._runtime.archive_thread(runtime_thread_id)
            finally:
                raise

    async def read_conversation(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        conversation = await self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
        async with self._lease_guard(conversation):
            return await self._runtime.read_thread(
                conversation.runtime_thread_id,
                conversation_id=conversation.id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            )

    async def compact_conversation(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> None:
        conversation = await self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
        async with self._lease_guard(conversation):
            await self._runtime.compact_thread(
                conversation.runtime_thread_id,
                conversation_id=conversation.id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            )

    async def chat(
        self,
        conversation_id: str,
        message: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> str:
        conversation = await self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
        async with self._lease_guard(conversation):
            return await self._runtime.run_turn(
                conversation.runtime_thread_id,
                conversation.id,
                message,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            )

    async def stream_chat(
        self,
        conversation_id: str,
        message: str,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> AsyncIterator[AgentEvent]:
        conversation = await self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
        async with self._lease_guard(conversation):
            async for event in self._runtime.stream_turn(
                conversation.runtime_thread_id,
                conversation.id,
                message,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ):
                yield event

    async def _resolve_and_acquire(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
        existing = await asyncio.to_thread(
            self._conversations.get_owned,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if existing.agent_id != self._agent_id or existing.runtime_type != "codex":
            raise RuntimeError("Conversation 与当前 Agent Runtime 不匹配")

        leased = await asyncio.to_thread(
            self._conversations.acquire_lease,
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            runtime_instance_id=self._runtime_instance_id,
            lease_seconds=self._runtime_lease_seconds,
        )
        if leased is None:
            raise RuntimeLeaseConflict(
                existing.runtime_lease_owner,
                existing.runtime_lease_expires_at,
            )
        return leased

    @asynccontextmanager
    async def _lease_guard(self, conversation: Conversation):
        """活跃 Turn 执行期间保持 lease，不允许另一个 Worker 在长请求中途接管。"""

        stop = asyncio.Event()
        lease_lost = asyncio.Event()
        owner_task = asyncio.current_task()

        async def heartbeat() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=self._heartbeat_interval_seconds,
                    )
                    return
                except TimeoutError:
                    renewed = await asyncio.to_thread(
                        self._conversations.renew_lease,
                        conversation.id,
                        runtime_instance_id=self._runtime_instance_id,
                        lease_seconds=self._runtime_lease_seconds,
                    )
                    if renewed:
                        continue
                    lease_lost.set()
                    if owner_task is not None:
                        owner_task.cancel()
                    return

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            yield
        except asyncio.CancelledError as exc:
            if lease_lost.is_set():
                raise RuntimeLeaseLost("活跃 Turn 的 Runtime lease 已丢失") from exc
            raise
        finally:
            stop.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
