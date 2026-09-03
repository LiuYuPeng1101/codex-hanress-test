from collections.abc import AsyncIterator
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


class AgentService:
    """企业 Agent 应用服务。

    外部只处理 business conversation_id。每次执行前原子续租或接管 Runtime lease；
    因此 Worker 实例不是永久归属。真正能否在新 Worker 恢复 Thread，取决于 CODEX_HOME
    是否部署在可恢复的持久存储上。
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
            return self._conversations.create(
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
        conversation = self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
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
        conversation = self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
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
        conversation = self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
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
        conversation = self._resolve_and_acquire(
            conversation_id, tenant_id=tenant_id, user_id=user_id
        )
        async for event in self._runtime.stream_turn(
            conversation.runtime_thread_id,
            conversation.id,
            message,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        ):
            yield event

    def _resolve_and_acquire(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
        existing = self._conversations.get_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if existing.agent_id != self._agent_id or existing.runtime_type != "codex":
            raise RuntimeError("Conversation 与当前 Agent Runtime 不匹配")

        leased = self._conversations.acquire_lease(
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
