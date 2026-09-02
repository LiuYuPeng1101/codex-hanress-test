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
    业务 conversation_id、身份和租户属于上层控制面，但 Runtime 负责把可信身份作为
    MCP HTTP Header 注入 Codex Thread 配置，确保业务身份不进入模型可伪造的 Tool 参数。
    """

    def __init__(
        self,
        workspace: Path,
        order_mcp_url: str,
        order_mcp_service_token: str,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._workspace = workspace.resolve()
        self._order_mcp_service_token = order_mcp_service_token
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
        # 私有 SDK 适配被严格限制在 Runtime Adapter 内，避免上层代码依赖 SDK 内部结构。
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

    async def create_thread(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> str:
        """创建人工 reviewer + read-only Sandbox 的 Codex Thread。

        `config` 中注入的 MCP Header 属于 Runtime 控制面，不出现在用户 Prompt 或 Tool Schema 中。
        """

        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            sandbox=SandboxMode.read_only,
            config=self._mcp_identity_config(user_id=user_id, tenant_id=tenant_id, roles=roles),
            cwd=str(self._workspace),
        )
        started = await self._codex._client.thread_start(params)
        return started.thread.id

    async def archive_thread(self, thread_id: str) -> None:
        self._ensure_started()
        await self._codex.thread_archive(thread_id)

    async def read_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        self._ensure_started()
        thread = await self._resume_thread(
            thread_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        response = await thread.read(include_turns=True)
        return response.model_dump(by_alias=True, mode="json")

    async def compact_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> None:
        self._ensure_started()
        thread = await self._resume_thread(
            thread_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        await thread.compact()

    async def run_turn(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> str:
        self._ensure_started()
        with self._tracer.start_as_current_span("agent.turn") as span:
            span.set_attribute("agent.conversation.id", conversation_id)
            span.set_attribute("agent.runtime.thread.id", thread_id)
            span.set_attribute("enduser.id", user_id)
            span.set_attribute("tenant.id", tenant_id)
            span.set_attribute("agent.streaming", False)
            span.set_attribute("agent.sandbox", Sandbox.read_only.value)

            thread = await self._resume_thread(
                thread_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
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
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> AsyncIterator[AgentEvent]:
        self._ensure_started()
        thread = await self._resume_thread(
            thread_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        turn = await thread.turn(message, sandbox=Sandbox.read_only)

        with self._tracer.start_as_current_span("agent.turn.stream") as span:
            span.set_attribute("agent.conversation.id", conversation_id)
            span.set_attribute("agent.runtime.thread.id", thread_id)
            span.set_attribute("agent.runtime.turn.id", turn.id)
            span.set_attribute("enduser.id", user_id)
            span.set_attribute("tenant.id", tenant_id)
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

    async def _resume_thread(
        self,
        thread_id: str,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> AsyncThread:
        """恢复 Thread 时重新注入当前可信身份，避免长期会话使用过期角色。"""

        return await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
            sandbox=Sandbox.read_only,
            config=self._mcp_identity_config(user_id=user_id, tenant_id=tenant_id, roles=roles),
        )

    def _mcp_identity_config(
        self,
        *,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        """构造 Codex Thread 级 MCP HTTP Header 配置。"""

        return {
            "mcp_servers.order.http_headers": {
                "Authorization": f"Bearer {self._order_mcp_service_token}",
                "X-User-Id": user_id,
                "X-Tenant-Id": tenant_id,
                "X-Roles": ",".join(sorted(roles)),
            }
        }

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
