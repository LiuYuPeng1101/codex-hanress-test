from collections.abc import AsyncIterator
from typing import Any

from app.events.models import AgentEvent
from app.runtime.codex_runtime import CodexRuntime


class AgentService:
    """Agent 应用服务。

    这一层组织 Thread / Turn / Context 管理等应用用例。
    API 层不直接操作 Codex SDK，Runtime 细节统一封装在 CodexRuntime。
    """

    def __init__(self, runtime: CodexRuntime) -> None:
        self._runtime = runtime

    async def create_conversation(self) -> str:
        """创建一个新的 Agent 会话并返回 Thread ID。"""

        return await self._runtime.create_thread()

    async def read_conversation(self, thread_id: str) -> dict[str, Any]:
        """读取 Thread 快照，并包含 Turn 历史。"""

        return await self._runtime.read_thread(thread_id)

    async def compact_conversation(self, thread_id: str) -> None:
        """触发指定 Thread 的手动 Compaction。"""

        await self._runtime.compact_thread(thread_id)

    async def chat(self, thread_id: str, message: str) -> str:
        """在指定 Thread 中执行一轮非流式 Turn。"""

        return await self._runtime.run_turn(thread_id, message)

    async def stream_chat(self, thread_id: str, message: str) -> AsyncIterator[AgentEvent]:
        """在指定 Thread 中执行一轮流式 Turn，并输出标准化 Agent Event。"""

        async for event in self._runtime.stream_turn(thread_id, message):
            yield event
