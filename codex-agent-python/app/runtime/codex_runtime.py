import json
from collections.abc import AsyncIterator
from typing import Any, Callable

from openai_codex import AsyncCodex, AsyncThread, CodexConfig, Sandbox
from openai_codex.generated.v2_all import (
    ApprovalsReviewer,
    AskForApproval,
    AskForApprovalValue,
    SandboxMode,
    SkillsListParams,
    SkillsListResponse,
    ThreadStartParams,
)

from app.agents.definitions import AgentDefinition
from app.events.codex_event_mapper import CodexEventMapper
from app.events.models import AgentEvent
from app.observability.tracing import get_tracer


class CodexRuntime:
    """Codex Harness 的生产级 Runtime Adapter。

    Runtime 只负责把通用 AgentDefinition 转换成 Codex Thread / Turn / Skill / MCP /
    Approval / Sandbox / Event / Context 调用，不包含订单、合同、客服等具体业务逻辑。
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
        # SDK 私有适配严格限制在 Runtime Adapter 内，业务层不依赖内部结构。
        self._codex._client._sync._approval_handler = approval_handler
        self._started = False

    @property
    def agent_id(self) -> str:
        return self._definition.id

    async def start(self) -> None:
        """启动 Runtime，并验证 Agent Definition 对 Codex 来说真实可运行。"""

        if self._started:
            return
        await self._codex.__aenter__()
        try:
            await self._validate_required_skills()
        except Exception:
            await self._codex.__aexit__(None, None, None)
            raise
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        await self._codex.__aexit__(None, None, None)
        self._started = False

    async def create_thread(self) -> str:
        """按照 Agent Definition 创建 Codex Thread。"""

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
        self._ensure_started()
        thread = await self._resume_thread(thread_id)
        response = await thread.read(include_turns=True)
        return response.model_dump(by_alias=True, mode="json")

    async def compact_thread(self, thread_id: str) -> None:
        """触发 Codex thread/compact/start。"""

        self._ensure_started()
        thread = await self._resume_thread(thread_id)
        await thread.compact()

    async def _resume_thread(self, thread_id: str) -> AsyncThread:
        return await self._codex.thread_resume(
            thread_id,
            cwd=str(self._definition.workspace),
        )

    async def _validate_required_skills(self) -> None:
        """通过 Codex skills/list 校验 Agent Definition 的必需 Skill。

        required_skills 不是文档字段：缺失或被禁用时服务启动失败，避免 Agent 进入半可用状态。
        """

        if not self._definition.required_skills:
            return

        params = SkillsListParams(
            cwds=[str(self._definition.workspace)],
            force_reload=True,
        )
        response = await self._codex._client.request(
            "skills/list",
            params.model_dump(by_alias=True, exclude_none=True, mode="json"),
            response_model=SkillsListResponse,
        )

        discovered = {
            skill.name
            for entry in response.data
            for skill in entry.skills
            if skill.enabled
        }
        missing = set(self._definition.required_skills) - discovered
        if missing:
            raise RuntimeError(
                f"Agent '{self._definition.id}' 缺少必需 Skill: {sorted(missing)}; "
                f"workspace={self._definition.workspace}"
            )

    def _decorate_span(self, span, thread_id: str, *, streaming: bool) -> None:
        span.set_attribute("agent.id", self._definition.id)
        span.set_attribute("agent.runtime", "codex")
        span.set_attribute("agent.thread.id", thread_id)
        span.set_attribute("agent.streaming", streaming)
        span.set_attribute("agent.sandbox", self._definition.sandbox.value)

    @staticmethod
    def _build_config_overrides(definition: AgentDefinition) -> tuple[str, ...]:
        """把平台无关 Agent Definition 编译成 Codex MCP 配置。"""

        overrides: list[str] = []
        for server in definition.mcp_servers:
            prefix = f"mcp_servers.{server.name}"
            overrides.extend(
                [
                    f"{prefix}.url={json.dumps(server.url)}",
                    f"{prefix}.required={json.dumps(server.required)}",
                    f"{prefix}.startup_timeout_sec={server.startup_timeout_sec}",
                    f"{prefix}.tool_timeout_sec={server.tool_timeout_sec}",
                    f"{prefix}.enabled_tools={json.dumps([tool.name for tool in server.tools])}",
                    f"{prefix}.default_tools_approval_mode={json.dumps(server.default_approval_mode)}",
                ]
            )
            for tool in server.tools:
                tool_prefix = f"{prefix}.tools.{tool.name}"
                overrides.extend(
                    [
                        f"{tool_prefix}.approval_mode={json.dumps(tool.approval_mode)}",
                        f"{tool_prefix}.output_token_limit={tool.output_token_limit}",
                    ]
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
