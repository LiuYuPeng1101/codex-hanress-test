from collections.abc import AsyncIterator
from typing import Any

from app.conversations.repository import Conversation, ConversationRepository
from app.events.models import AgentEvent
from app.runtime.codex_runtime import CodexRuntime


class AgentService:
    """平台层 Agent 应用服务。

    业务 API 只使用 conversation_id；Codex thread_id 被封装成 Runtime 私有标识。
    """

    def __init__(
        self,
        runtime: CodexRuntime,
        conversations: ConversationRepository,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations

    async def create_conversation(self, agent_id: str) -> Conversation:
        self._ensure_agent(agent_id)
        runtime_thread_id = await self._runtime.create_thread()
        return self._conversations.create(
            agent_id=agent_id,
            runtime="codex",
            runtime_thread_id=runtime_thread_id,
        )

    async def read_conversation(self, agent_id: str, conversation_id: str) -> dict[str, Any]:
        conversation = self._resolve(agent_id, conversation_id)
        return await self._runtime.read_thread(conversation.runtime_thread_id)

    async def compact_conversation(self, agent_id: str, conversation_id: str) -> None:
        conversation = self._resolve(agent_id, conversation_id)
        await self._runtime.compact_thread(conversation.runtime_thread_id)

    async def chat(self, agent_id: str, conversation_id: str, message: str) -> str:
        conversation = self._resolve(agent_id, conversation_id)
        return await self._runtime.run_turn(conversation.runtime_thread_id, message)

    async def stream_chat(
        self,
        agent_id: str,
        conversation_id: str,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        conversation = self._resolve(agent_id, conversation_id)
        async for event in self._runtime.stream_turn(conversation.runtime_thread_id, message):
            yield event

    def get_conversation(self, agent_id: str, conversation_id: str) -> Conversation:
        return self._resolve(agent_id, conversation_id)

    def _resolve(self, agent_id: str, conversation_id: str) -> Conversation:
        self._ensure_agent(agent_id)
        conversation = self._conversations.get(conversation_id)
        if conversation.agent_id != agent_id:
            raise KeyError(conversation_id)
        if conversation.runtime != "codex":
            raise RuntimeError(f"当前 Runtime 不支持: {conversation.runtime}")
        return conversation

    def _ensure_agent(self, agent_id: str) -> None:
        if agent_id != self._runtime.agent_id:
            raise KeyError(agent_id)
