import json
from pathlib import Path

from openai_codex import AsyncCodex, CodexConfig, Sandbox


class CodexRuntime:
    """对官方 OpenAI Codex Python SDK 的轻量封装。

    这一层只负责 Codex Runtime 能力，不应该放具体订单、财务、合同业务逻辑。
    FastAPI 启动时创建一份 Runtime，应用关闭时统一释放。

    当前 Runtime 会把 Java 业务系统的订单 MCP Server 注入 Codex 配置。
    Tool 的发现、参数 Schema、调用和结果回传仍由 Codex Harness 负责，
    Python Agent Service 不自己实现 MCP Client。
    """

    def __init__(self, workspace: Path, order_mcp_url: str) -> None:
        self._workspace = workspace.resolve()
        self._order_mcp_url = order_mcp_url

        # CodexConfig.config_overrides 最终会转换成 codex --config key=value。
        # 这里先只开放只读 Tool get_order_status，避免学习阶段把写操作暴露给 Agent。
        # URL 使用 json.dumps 生成带引号的字符串，避免手工拼 TOML 字符串时转义出错。
        config = CodexConfig(
            config_overrides=(
                f"mcp_servers.order.url={json.dumps(order_mcp_url)}",
                'mcp_servers.order.enabled_tools=["get_order_status"]',
                'mcp_servers.order.default_tools_approval_mode="approve"',
            )
        )

        self._codex = AsyncCodex(config=config)
        self._started = False

    @property
    def workspace(self) -> Path:
        """返回当前 Agent 的工作目录。"""

        return self._workspace

    @property
    def order_mcp_url(self) -> str:
        """返回当前订单 MCP Server 地址，主要用于日志、健康检查和问题排查。"""

        return self._order_mcp_url

    async def start(self) -> None:
        """启动 Codex Runtime。

        AsyncCodex 使用懒初始化机制；进入异步上下文会启动底层 Codex Runtime。
        这里显式管理生命周期，方便与 FastAPI lifespan 对齐。

        启动后 Codex Runtime 会读取上面的 MCP 配置；真正的 MCP 连接通常在
        Thread/Turn 运行过程中按 Runtime 机制建立和使用。
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

        例如用户询问订单 1001 状态时，order-analysis Skill 会要求不要猜测实时状态；
        Codex Harness 可以发现订单 MCP 的 get_order_status Tool，调用 Java 业务系统，
        再把 Tool 返回的数据交给模型生成最终答案。
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
