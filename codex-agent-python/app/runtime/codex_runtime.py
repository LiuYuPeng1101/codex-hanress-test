import json
import os
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

from app.agents.definition import AgentDefinition, SandboxPolicy
from app.events.codex_event_mapper import CodexEventMapper
from app.events.models import AgentEvent
from app.observability.tracing import get_tracer
from app.security.runtime_identity import RuntimeIdentityIssuer


class CodexRuntime:
    """把企业 AgentDefinition 适配到官方 Codex Harness。

    Codex Harness 仍负责 Thread、Turn、Context、Compaction、Sandbox 与 Tool Loop；
    但 LLM / MCP 网络出口都被改写到 agentgateway。Runtime 不持有 OpenAI/MCP 后端凭证。
    """

    def __init__(
        self,
        definition: AgentDefinition,
        codex_home: Path,
        approval_handler: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        runtime_identity_issuer: RuntimeIdentityIssuer,
    ) -> None:
        self._definition = definition
        self._workspace = Path(definition.workspace).resolve()
        self._codex_home = codex_home.resolve()
        self._runtime_identity_issuer = runtime_identity_issuer
        self._event_mapper = CodexEventMapper()
        self._tracer = get_tracer()

        self._codex_home.mkdir(parents=True, exist_ok=True)
        if not os.access(self._codex_home, os.W_OK):
            raise RuntimeError(f"Codex 持久化目录不可写: {self._codex_home}")

        runtime_env = dict(os.environ)
        runtime_env["CODEX_HOME"] = str(self._codex_home)

        self._codex = AsyncCodex(
            config=CodexConfig(
                env=runtime_env,
                config_overrides=self._build_runtime_config_overrides(),
            )
        )

        # 当前高层 AsyncCodex 尚未直接暴露人工 approval handler。
        # 私有 SDK 适配被严格限制在 Runtime Adapter 内；SDK 升级时只需修改这一处。
        self._codex._client._sync._approval_handler = approval_handler
        self._started = False

    @property
    def agent_id(self) -> str:
        return self._definition.agent_id

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
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> str:
        self._ensure_started()
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=ApprovalsReviewer.user,
            sandbox=self._sandbox_mode(),
            config=self._gateway_identity_config(
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ),
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
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        thread = await self._resume_thread(
            thread_id,
            conversation_id=conversation_id,
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
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> None:
        thread = await self._resume_thread(
            thread_id,
            conversation_id=conversation_id,
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
        with self._tracer.start_as_current_span("agent.turn") as span:
            self._set_common_span_attributes(span, conversation_id, thread_id, user_id, tenant_id)
            span.set_attribute("agent.streaming", False)

            thread = await self._resume_thread(
                thread_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            )
            result = await thread.run(message, sandbox=self._sandbox())

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
        thread = await self._resume_thread(
            thread_id,
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )
        turn = await thread.turn(message, sandbox=self._sandbox())

        with self._tracer.start_as_current_span("agent.turn.stream") as span:
            self._set_common_span_attributes(span, conversation_id, thread_id, user_id, tenant_id)
            span.set_attribute("agent.runtime.turn.id", turn.id)
            span.set_attribute("agent.streaming", True)

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
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> AsyncThread:
        """恢复 Thread 时重新签发短期身份，避免长期会话沿用过期权限。"""

        self._ensure_started()
        return await self._codex.thread_resume(
            thread_id,
            cwd=str(self._workspace),
            sandbox=self._sandbox(),
            config=self._gateway_identity_config(
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
            ),
        )

    def _build_runtime_config_overrides(self) -> tuple[str, ...]:
        """启动 Codex 时固定所有网络型能力的逻辑出口。"""

        model_gateway = self._definition.model_gateway
        provider = f"model_providers.{model_gateway.provider_id}"
        overrides: list[str] = [
            f"model_provider={json.dumps(model_gateway.provider_id)}",
            f"model={json.dumps(model_gateway.model)}",
            f"{provider}.name={json.dumps('Agent Gateway')}",
            f"{provider}.base_url={json.dumps(model_gateway.base_url)}",
            f"{provider}.wire_api={json.dumps('responses')}",
            f"{provider}.requires_openai_auth=false",
        ]

        for server in self._definition.mcp_servers:
            prefix = f"mcp_servers.{server.name}"
            overrides.extend(
                [
                    f"{prefix}.url={json.dumps(server.url)}",
                    f"{prefix}.enabled_tools={json.dumps(list(server.enabled_tools))}",
                    f"{prefix}.default_tools_approval_mode={json.dumps(server.default_approval_mode)}",
                ]
            )
            for tool_name, approval_mode in server.tool_approval_modes:
                overrides.append(
                    f"{prefix}.tools.{tool_name}.approval_mode={json.dumps(approval_mode)}"
                )
        return tuple(overrides)

    def _gateway_identity_config(
        self,
        *,
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        roles: frozenset[str],
    ) -> dict[str, Any]:
        """同一短期内部 JWT 同时标识本 Turn 的 LLM 与 MCP 出站身份。"""

        token = self._runtime_identity_issuer.issue(
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            agent_id=self._definition.agent_id,
            roles=roles,
        )
        authorization = f"Bearer {token}"
        config: dict[str, Any] = {
            f"model_providers.{self._definition.model_gateway.provider_id}.http_headers": {
                "Authorization": authorization,
            }
        }
        for server in self._definition.mcp_servers:
            config[f"mcp_servers.{server.name}.http_headers"] = {
                "Authorization": authorization,
            }
        return config

    def _sandbox(self) -> Sandbox:
        return {
            SandboxPolicy.READ_ONLY: Sandbox.read_only,
            SandboxPolicy.WORKSPACE_WRITE: Sandbox.workspace_write,
            SandboxPolicy.FULL_ACCESS: Sandbox.full_access,
        }[self._definition.sandbox]

    def _sandbox_mode(self) -> SandboxMode:
        return {
            SandboxPolicy.READ_ONLY: SandboxMode.read_only,
            SandboxPolicy.WORKSPACE_WRITE: SandboxMode.workspace_write,
            SandboxPolicy.FULL_ACCESS: SandboxMode.danger_full_access,
        }[self._definition.sandbox]

    def _set_common_span_attributes(
        self,
        span: Any,
        conversation_id: str,
        thread_id: str,
        user_id: str,
        tenant_id: str,
    ) -> None:
        span.set_attribute("agent.id", self._definition.agent_id)
        span.set_attribute("agent.conversation.id", conversation_id)
        span.set_attribute("agent.runtime.type", "codex")
        span.set_attribute("agent.runtime.thread.id", thread_id)
        span.set_attribute("agent.sandbox", self._sandbox().value)
        span.set_attribute("enduser.id", user_id)
        span.set_attribute("tenant.id", tenant_id)

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Codex Runtime 尚未启动")
