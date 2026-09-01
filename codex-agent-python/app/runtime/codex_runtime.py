from pathlib import Path

from openai_codex import AsyncCodex, Sandbox


class CodexRuntime:
    """对官方 OpenAI Codex Python SDK 的轻量封装。

    这一层只负责 Codex Runtime 能力，不应该放具体订单、财务、合同业务逻辑。
    FastAPI 启动时创建一份 Runtime，应用关闭时统一释放。
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()
        self._codex = AsyncCodex()
        self._started = False

    @property
    def workspace(self) -> Path:
        """返回当前 Agent 的工作目录。"""

        return self._workspace

    async def start(self) -> None:
        """启动 Codex Runtime。

        AsyncCodex 使用懒初始化机制；进入异步上下文会启动底层 Codex Runtime。
        这里显式管理生命周期，方便与 FastAPI lifespan 对齐。
        """

        if self._started:
            return
        await self._codex.__aenter__()
        self._started = True

    async def close(self) -> None:
        """关闭 Codex Runtime 并释放底层进程资源。"""

        if not self._started:
            return
        await self._codex.__aexit__(None, None, None)
        self._started = False

    async def create_thread(self) -> str:
        """创建一个新的 Codex Thread。

        Thread 可以理解成一个持续存在的 Agent 聊天窗口。
        cwd 指向 Agent workspace，Codex 可以据此发现 workspace 下的 `.agents/skills`。
        """

        self._ensure_started()
        thread = await self._codex.thread_start(
            cwd=str(self._workspace),
            sandbox=Sandbox.workspace_write,
        )
        return thread.id

    async def run_turn(self, thread_id: str, message: str) -> str:
        """在已有 Thread 中执行一轮 Turn，并返回最终回答。

        Turn 表示一次完整的 Agent 执行：用户输入、模型推理、Skill、MCP/Tool 调用，
        直到本轮执行完成。
        """

        self._ensure_started()
        thread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        result = await thread.run(message)
        return result.final_response

    def _ensure_started(self) -> None:
        """防止在 FastAPI 生命周期尚未启动完成时调用 Runtime。"""

        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
