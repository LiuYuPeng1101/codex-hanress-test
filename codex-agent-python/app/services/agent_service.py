from app.runtime.codex_runtime import CodexRuntime


class AgentService:
    """Agent 应用服务。

    这一层负责组织“创建会话、执行一轮对话”等应用用例。
    API 层不直接操作 Codex SDK，后续如果增加权限、审计、Agent Definition，
    都可以优先放在这一层或它的上游。
    """

    def __init__(self, runtime: CodexRuntime) -> None:
        self._runtime = runtime

    async def create_conversation(self) -> str:
        """创建一个新的 Agent 会话并返回 Thread ID。"""

        return await self._runtime.create_thread()

    async def chat(self, thread_id: str, message: str) -> str:
        """在指定 Thread 中执行一轮 Turn。"""

        return await self._runtime.run_turn(thread_id, message)
