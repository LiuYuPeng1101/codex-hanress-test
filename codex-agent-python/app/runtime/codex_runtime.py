import json
from collections.abc import AsyncIterator
from typing import Any, Callable

from openai_codex import AsyncCodex, AsyncThread, CodexConfig, Sandbox
from openai_codex.generated.v2_all import (
    ApprovalsReviewer,
    AskForApproval,
    AskForApprovalValue,
    SandboxMode,
    ThreadStartParams,
)

from app.agents.definitions import AgentDefinition
from app.events.codex_event_mapper import CodexEventMapper
from app.events.models import AgentEvent
from app.observability.tracing import get_tracer


class CodexRuntime:
    """Codex Harness 的生产级 Runtime Adapter。

    Runtime 只负责把通用 AgentDefinition 转换成 Codex Thread / Turn / MCP / Sandbox /
    Approval / Event 调用，不包含订单、合同、客服等任何具体业务逻辑。
    """

    def __init__(
        self,
        definition: AgentDefinition,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._definition = definition
        self._event_mapper = CodexEventMapper()
        self._tracer = get_tracer()

        self._codex = AsyncCodex(
            config=CodexConfig(config_overrides=self._build_config_overrides(definition))
        )

        # 当前官方 AsyncCodex 高层构造器暂未直接暴露 approval_handler。
        # 将 SDK 私有适配严格限制在 Runtime Adapter 内，业务层不依赖该内部结构。
        self._codex._client._sync._approval_handler = approval_handler
        self._started = False

    @property
    def agent_id(self) -> str:
        return self._definition.id

    async def start(self) -> None:
        """启动 Codex Runtime 连接。"""

        if self._started:
            return
        await self._codex.__aenter__()
        self._started = True

    async def close(self) -> None:
        """关闭 Codex Runtime 连接并释放底层进程资源。"""

        if not self._started:
            return
        await self._codex.__aexit__(None, None, None)
        self._started = False

    async def create_thread(self) -> str:
        """按照 Agent Definition 创建一个 Codex Thread。"""

        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            sandbox=self._sandbox_mode(self._definition.sandbox),
            cwd=str(self._definition.workspace),
        )
        started = await self._codex._client.thread_start(params)
        return started.thread.id

    async def run_turn(self, thread_id: str, message: str) -> str:
        """在已有 Thread 上执行一轮非流式 Turn。"""

        self._ensure_started()
        with self._tracer.start_as_current_span("agent.turn") as span:
            self._decorate_span(span, thread_id, streaming=False)

            thread = await self._resume_thread(thread_id)
            result = await thread.run(message, sandbox=self._definition.sandbox)

            span.set_attribute("agent.turn.id", result.id)
            span.set_attribute("agent.turn.status", str(result.status))
            if result.duration_ms is not None:
                span.set_attribute("agent.turn.duration_ms", result.duration_ms)
            return result.final_response or ""

    async def stream_turn(self, thread_id: str, message: str) -> AsyncIterator[AgentEvent]:
        """执行流式 Turn，并输出经过稳定协议映射的 AgentEvent。"""

        self._ensure_started()
        thread = await self._resume_thread(thread_id)
        turn = await thread.turn(message, sandbox=self._definition.sandbox)

        with self._tracer.start_as_current_span("agent.turn.stream") as span:
            self._decorate_span(span, thread_id, streaming=True)
            span.set_attribute("agent.turn.id", turn.id)

            async for notification in turn.stream():
                event = self._event_mapper.map(notification, thread_id, turn.id)
                if event is None:
                    continue

                attributes: dict[str, str] = {
                    "agent.event.type": event.type,
                    "agent.id": self._definition.id,
                    "agent.thread.id": thread_id,
                    "agent.turn.id": turn.id,
                }
                tool_name = event.data.get("tool_name")
                if tool_name:
                    attributes["agent.tool.name"] = str(tool_name)
                span.add_event(event.type, attributes=attributes)
                yield event

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        """读取 Codex 持久化 Thread 与 Turn 历史。"""

        self._ensure_started()
        thread = await self._resume_thread(thread_id)
        response = await thread.read(include_turns=True)
        return response.model_dump(by_alias=True, mode="json")

    async def compact_thread(self, thread_id: str) -> None:
        """触发 Codex Thread Compaction。

        官方接口是 thread/compact/start，因此本方法只保证压缩请求已被接受，不把它伪装成同步完成。
        """

        self._ensure_started()
        thread = await self._resume_thread(thread_id)
        await thread.compact()

    async def _resume_thread(self, thread_id: str) -> AsyncThread:
        """从 Codex 持久化状态恢复 Thread，而不是依赖 Python 进程内对象缓存。"""

        return await self._codex.thread_resume(
            thread_id,
            cwd=str(self._definition.workspace),
        )

    def _decorate_span(self, span, thread_id: str, *, streaming: bool) -> None:
        span.set_attribute("agent.id", self._definition.id)
        span.set_attribute("agent.runtime", "codex")
        span.set_attribute("agent.thread.id", thread_id)
        span.set_attribute("agent.streaming", streaming)
        span.set_attribute("agent.sandbox", self._definition.sandbox.value)

    @staticmethod
    def _build_config_overrides(definition: AgentDefinition) -> tuple[str, ...]:
        overrides: list[str] = []
        for server in definition.mcp_servers:
            prefix = f"mcp_servers.{server.name}"
            overrides.append(f"{prefix}.url={json.dumps(server.url)}")
            overrides.append(
                f"{prefix}.enabled_tools={json.dumps([tool.name for tool in server.tools])}"
            )
            overrides.append(
                f"{prefix}.default_tools_approval_mode={json.dumps(server.default_approval_mode)}"
            )
            for tool in server.tools:
                overrides.append(
                    f"{prefix}.tools.{tool.name}.approval_mode={json.dumps(tool.approval_mode)}"
                )
        return tuple(overrides)

    @staticmethod
    def _sandbox_mode(sandbox: Sandbox) -> SandboxMode:
        if sandbox is Sandbox.read_only:
            return SandboxMode.read_only
        if sandbox is Sandbox.workspace_write:
            return SandboxMode.workspace_write
        if sandbox is Sandbox.full_access:
            return SandboxMode.danger_full_access
        raise ValueError(f"不支持的 Sandbox: {sandbox}")

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
