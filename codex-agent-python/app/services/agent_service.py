from collections.abc import AsyncIterator
from typing import Any

from app.conversations.conversation_repository import Conversation, ConversationRepository
from app.events.models import AgentEvent
from app.runtime.codex_runtime import CodexRuntime


class AgentService:
    """单 Agent 的应用服务。

    外部只处理业务 conversation_id；内部把它映射为 Codex thread_id。
    这里不做 Agent Registry、Runtime Scheduler、Lease 或多 Runtime 路由。
    """

    def __init__(
        self,
        runtime: CodexRuntime,
        conversations: ConversationRepository,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> Conversation:
        conversation_id = self._conversations.new_id()
        runtime_thread_id = await self._runtime.create_thread(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        try:
            return self._conversations.create(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                runtime_thread_id=runtime_thread_id,
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
        conversation = self._resolve_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return await self._runtime.read_thread(
            conversation.runtime_thread_id,
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
        conversation = self._resolve_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await self._runtime.compact_thread(
            conversation.runtime_thread_id,
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
        conversation = self._resolve_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
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
        conversation = self._resolve_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
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

    def _resolve_owned(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
        return self._conversations.get_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
