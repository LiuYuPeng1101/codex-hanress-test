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
    """官方 OpenAI Codex Python SDK 的企业 Runtime Adapter。

    Runtime 只处理 Codex Thread / Turn / Sandbox / Approval / Event / Context 等执行能力。
    业务 conversation_id、用户、租户和 Agent Definition 由上层控制面管理。
    """

    def __init__(
        self,
        workspace: Path,
        order_mcp_url: str,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._workspace = workspace.resolve()
        self._event_mapper = CodexEventMapper()
        self._tracer = get_tracer()

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

        # 当前高层 AsyncCodex 尚未直接暴露人工 approval handler。
        # 这段私有 SDK 适配被严格限制在 Runtime Adapter 内。
        self._codex._client._sync._approval_handler = approval_handler
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self._codex.__aenter__()
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        await self._codex.__aexit__(None, None, None)
        self._started = False

    async def create_thread(self) -> str:
        """创建人工 reviewer + read-only Sandbox 的 Codex Thread。"""

        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            sandbox=SandboxMode.read_only,
            cwd=str(self._workspace),
        )
        started = await self._codex._client.thread_start(params)
        return started.thread.id

    async def archive_thread(self, thread_id: str) -> None:
        """归档无法绑定到业务 Conversation 的孤儿 Thread。"""

        self._ensure_started()
        await self._codex.thread_archive(thread_id)

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        response = await thread.read(include_turns=True)
        return response.model_dump(by_alias=True, mode="json")

    async def compact_thread(self, thread_id: str) -> None:
        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        await thread.compact()

    async def run_turn(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
    ) -> str:
        self._ensure_started()
        with self._tracer.start_as_current_span("agent.turn") as span:
            span.set_attribute("agent.conversation.id", conversation_id)
            span.set_attribute("agent.runtime.thread.id", thread_id)
            span.set_attribute("agent.streaming", False)
            span.set_attribute("agent.sandbox", Sandbox.read_only.value)

            thread: AsyncThread = await self._codex.thread_resume(
                thread_id,
                cwd=str(self._workspace),
            )
            result = await thread.run(message, sandbox=Sandbox.read_only)

            span.set_attribute("agent.runtime.turn.id", result.id)
            span.set_attribute("agent.turn.status", str(result.status))
            if result.duration_ms is not None:
                span.set_attribute("agent.turn.duration_ms", result.duration_ms)
            return result.final_response or ""

    async def stream_turn(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        self._ensure_started()
        thread: AsyncThread = await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
        )
        turn = await thread.turn(message, sandbox=Sandbox.read_only)

        with self._tracer.start_as_current_span("agent.turn.stream") as span:
            span.set_attribute("agent.conversation.id", conversation_id)
            span.set_attribute("agent.runtime.thread.id", thread_id)
            span.set_attribute("agent.runtime.turn.id", turn.id)
            span.set_attribute("agent.streaming", True)
            span.set_attribute("agent.sandbox", Sandbox.read_only.value)

            async for notification in turn.stream():
                event = self._event_mapper.map(notification, conversation_id)
                if event is None:
                    continue

                attributes: dict[str, str] = {
                    "agent.event.type": event.type,
                    "agent.conversation.id": conversation_id,
                    "agent.runtime.thread.id": thread_id,
                    "agent.runtime.turn.id": turn.id,
                }
                tool_name = event.data.get("tool_name")
                if tool_name:
                    attributes["agent.tool.name"] = str(tool_name)
                span.add_event(event.type, attributes=attributes)
                yield event

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
