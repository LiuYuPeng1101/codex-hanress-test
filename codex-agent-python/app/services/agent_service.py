from collections.abc import AsyncIterator
from typing import Any

from app.conversations.conversation_repository import Conversation, ConversationRepository
from app.events.models import AgentEvent
from app.runtime.codex_runtime import CodexRuntime


class RuntimeOwnershipError(RuntimeError):
    """当前请求没有路由到持有该 Runtime Thread 的实例。"""

    def __init__(self, expected_instance_id: str) -> None:
        super().__init__(f"Conversation 应路由到 Runtime 实例: {expected_instance_id}")
        self.expected_instance_id = expected_instance_id


class AgentService:
    """企业 Agent 应用服务。

    外部只处理 business conversation_id。Codex thread_id 始终保留在 Runtime 映射内部。
    当前调用者的角色不写死到 Conversation 中，而是每次请求由可信 Gateway 重新注入，
    再通过 Runtime Thread config 传给 MCP，避免长期会话沿用过期授权。
    """

    def __init__(
        self,
        runtime: CodexRuntime,
        conversations: ConversationRepository,
        *,
        agent_id: str,
        runtime_instance_id: str,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self._agent_id = agent_id
        self._runtime_instance_id = runtime_instance_id

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str,
        roles: frozenset[str],
    ) -> Conversation:
        runtime_thread_id = await self._runtime.create_thread(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        try:
            return self._conversations.create(
                agent_id=self._agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                runtime_type="codex",
                runtime_thread_id=runtime_thread_id,
                runtime_instance_id=self._runtime_instance_id,
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
        conversation = self._resolve_owned(conversation_id, tenant_id=tenant_id, user_id=user_id)
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
        conversation = self._resolve_owned(conversation_id, tenant_id=tenant_id, user_id=user_id)
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
        conversation = self._resolve_owned(conversation_id, tenant_id=tenant_id, user_id=user_id)
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
        conversation = self._resolve_owned(conversation_id, tenant_id=tenant_id, user_id=user_id)
        async for event in self._runtime.stream_turn(
            conversation.runtime_thread_id,
            conversation.id,
            message,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        ):
            yield event

    def _resolve_owned(self, conversation_id: str, *, tenant_id: str, user_id: str) -> Conversation:
        conversation = self._conversations.get_owned(
            conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if conversation.agent_id != self._agent_id or conversation.runtime_type != "codex":
            raise RuntimeError("Conversation 与当前 Agent Runtime 不匹配")
        if conversation.runtime_instance_id != self._runtime_instance_id:
            raise RuntimeOwnershipError(conversation.runtime_instance_id)
        return conversation
