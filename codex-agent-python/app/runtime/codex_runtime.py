import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Callable

from openai_codex import AsyncCodex, AsyncThread, CodexConfig, Sandbox
from openai_codex.generated.v2_all import (
    ApprovalsReviewer,
    AskForApproval,
    AskForApprovalValue,
    SandboxMode,
    ThreadStartParams,
)

from app.events.codex_event_mapper import CodexEventMapper
from app.events.models import AgentEvent
from app.observability.tracing import get_tracer


class CodexRuntime:
    """对官方 OpenAI Codex Python SDK 的轻量封装。

    这一层只负责 Codex Runtime 能力，不放具体订单、财务、合同业务逻辑。
    FastAPI 启动时创建一份 Runtime，应用关闭时统一释放。

    当前订单 Agent 使用：
    - Java MCP Server 提供真实业务能力；
    - Human Approval 控制高风险写操作；
    - read-only Sandbox 限制本地执行环境；
    - Event / SSE / OpenTelemetry 暴露运行过程；
    - Thread Read / Compaction 用于学习长会话上下文管理。
    """

    def __init__(
        self,
        workspace: Path,
        order_mcp_url: str,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._workspace = workspace.resolve()
        self._order_mcp_url = order_mcp_url
        self._event_mapper = CodexEventMapper()
        self._tracer = get_tracer()

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
        # 这里把 SDK 私有适配限制在 Runtime 内部，不让 API / Service 层依赖内部结构。
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
        """创建使用人工 reviewer + read-only Sandbox 的 Codex Thread。"""

        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            sandbox=SandboxMode.read_only,
            cwd=str(self._workspace),
        )
        started = await self._codex._client.thread_start(params)
        return started.thread.id

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        """读取 Thread 快照，并包含 Turn 历史。

        这里读取的是 Codex 持久化的 Thread/Turn 结构，主要用于学习和诊断。
        它不等于“下一次模型请求会把这些内容全部原样塞进 Context Window”。
        """

        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        response = await thread.read(include_turns=True)
        return response.model_dump(by_alias=True, mode="json")

    async def compact_thread(self, thread_id: str) -> None:
        """触发一次手动 Thread Compaction。

        官方接口是 `thread/compact/start`，因此这里的返回只表示已经成功发起压缩，
        不把“请求已受理”误写成“压缩已经同步完成”。
        """

        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        await thread.compact()

    async def run_turn(self, thread_id: str, message: str) -> str:
        """执行一轮非流式 Turn，兼容原有一次性返回最终答案的 API。"""

        self._ensure_started()
        with self._tracer.start_as_current_span("agent.turn") as span:
            span.set_attribute("agent.thread.id", thread_id)
            span.set_attribute("agent.streaming", False)
            span.set_attribute("agent.sandbox", Sandbox.read_only.value)

            thread: AsyncThread = await self._codex.thread_resume(
                thread_id,
                cwd=str(self._workspace),
            )
            result = await thread.run(
                message,
                sandbox=Sandbox.read_only,
            )

            span.set_attribute("agent.turn.id", result.id)
            span.set_attribute("agent.turn.status", str(result.status))
            if result.duration_ms is not None:
                span.set_attribute("agent.turn.duration_ms", result.duration_ms)

            return result.final_response or ""

    async def stream_turn(self, thread_id: str, message: str) -> AsyncIterator[AgentEvent]:
        """执行一轮流式 Turn，并逐条输出经过安全映射的 AgentEvent。"""

        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        turn = await thread.turn(
            message,
            sandbox=Sandbox.read_only,
        )

        with self._tracer.start_as_current_span("agent.turn.stream") as span:
            span.set_attribute("agent.thread.id", thread_id)
            span.set_attribute("agent.turn.id", turn.id)
            span.set_attribute("agent.streaming", True)
            span.set_attribute("agent.sandbox", Sandbox.read_only.value)

            async for notification in turn.stream():
                event = self._event_mapper.map(notification, thread_id, turn.id)
                if event is None:
                    continue

                attributes: dict[str, str] = {
                    "agent.event.type": event.type,
                    "agent.thread.id": thread_id,
                    "agent.turn.id": turn.id,
                }
                tool_name = event.data.get("tool_name")
                if tool_name:
                    attributes["agent.tool.name"] = str(tool_name)
                span.add_event(event.type, attributes=attributes)
                yield event

    def _ensure_started(self) -> None:
        """防止在 FastAPI 生命周期尚未启动完成时调用 Runtime。"""

        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
