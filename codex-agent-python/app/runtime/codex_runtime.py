import json
from pathlib import Path
from typing import Any, Callable

from openai_codex import AsyncCodex, AsyncThread, CodexConfig
from openai_codex.generated.v2_all import (
    ApprovalsReviewer,
    AskForApproval,
    AskForApprovalValue,
    ThreadStartParams,
)


class CodexRuntime:
    """对官方 OpenAI Codex Python SDK 的轻量封装。

    这一层只负责 Codex Runtime 能力，不应该放具体订单、财务、合同业务逻辑。
    FastAPI 启动时创建一份 Runtime，应用关闭时统一释放。

    当前 Runtime 会把 Java 业务系统的订单 MCP Server 注入 Codex 配置，并把
    MCP 写操作的 Approval Server Request 转给上层 ApprovalService 处理。
    """

    def __init__(
        self,
        workspace: Path,
        order_mcp_url: str,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._workspace = workspace.resolve()
        self._order_mcp_url = order_mcp_url

        # MCP Tool 策略：查询自动执行，取消订单必须进入 Approval。
        config = CodexConfig(
            config_overrides=(
                f"mcp_servers.order.url={json.dumps(order_mcp_url)}",
                'mcp_servers.order.enabled_tools=["get_order_status","cancel_order"]',
                'mcp_servers.order.default_tools_approval_mode="approve"',
                'mcp_servers.order.tools.get_order_status.approval_mode="approve"',
                'mcp_servers.order.tools.cancel_order.approval_mode="prompt"',
            )
        )

        self._codex = AsyncCodex(config=config)

        # 当前官方 AsyncCodex 高层构造器暂未直接暴露 approval_handler。
        # 但其内部 AsyncCodexClient 包装的是官方 CodexClient，后者原生支持 approval_handler。
        # 因此这里把适配限制在 Runtime 内部，不让 API / Service 层依赖 SDK 私有结构。
        self._codex._client._sync._approval_handler = approval_handler
        self._started = False

    @property
    def workspace(self) -> Path:
        """返回当前 Agent 的工作目录。"""

        return self._workspace

    @property
    def order_mcp_url(self) -> str:
        """返回当前订单 MCP Server 地址。"""

        return self._order_mcp_url

    async def start(self) -> None:
        """启动 Codex Runtime。"""

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
        """创建使用“人工 reviewer”的 Codex Thread。

        官方高层 ApprovalMode 当前主要暴露 auto_review / deny_all；底层 typed protocol
        已支持 ApprovalsReviewer.user，所以这里通过 SDK 自带的底层 typed client 创建 Thread。
        这样 MCP prompt approval 会真正路由到我们注入的 approval_handler，而不是自动审核。
        """

        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            cwd=str(self._workspace),
        )
        started = await self._codex._client.thread_start(params)
        return started.thread.id

    async def run_turn(self, thread_id: str, message: str) -> str:
        """在已有 Thread 中执行一轮 Turn，并返回最终回答。

        当本轮调用 cancel_order 时，Codex 会暂停在 MCP Tool Approval，直到
        ApprovalService 返回 accept 或 decline；查询类 get_order_status 不需要人工审批。
        """

        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        result = await thread.run(message)
        return result.final_response

    def _ensure_started(self) -> None:
        """防止在 FastAPI 生命周期尚未启动完成时调用 Runtime。"""

        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
