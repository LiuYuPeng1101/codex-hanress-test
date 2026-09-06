from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.agents.definition import AgentDefinition, McpServerDefinition, SandboxPolicy
from app.approval.approval_repository import ApprovalRepository
from app.approval.approval_service import ApprovalService
from app.conversations.conversation_repository import ConversationRepository
from app.core.config import get_settings
from app.observability.tracing import configure_tracing
from app.runtime.admission import AdmissionController
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """装配当前唯一 Agent 的生产依赖。"""

    settings = get_settings()
    configure_tracing(
        service_name=settings.app_name,
        otlp_endpoint=settings.otel_exporter_otlp_traces_endpoint,
    )

    async with AsyncExitStack() as stack:
        conversation_repository = ConversationRepository(settings.database_url)
        stack.callback(conversation_repository.close)
        approval_repository = ApprovalRepository(settings.database_url)
        stack.callback(approval_repository.close)
        await run_in_threadpool(conversation_repository.healthcheck)
        await run_in_threadpool(approval_repository.healthcheck)

        approval_service = ApprovalService(
            approval_repository,
            conversation_repository,
        )

        definition = AgentDefinition(
            agent_id=settings.agent_id,
            workspace=str(settings.agent_workspace),
            sandbox=SandboxPolicy.READ_ONLY,
            mcp_servers=(
                McpServerDefinition(
                    name="order",
                    url=settings.order_mcp_url,
                    service_token=settings.order_mcp_service_token,
                    enabled_tools=("get_order_status", "cancel_order"),
                    tool_approval_modes=(
                        ("get_order_status", "approve"),
                        ("cancel_order", "prompt"),
                    ),
                ),
            ),
        )

        runtime = CodexRuntime(
            definition=definition,
            codex_home=settings.codex_home,
            approval_handler=approval_service.handle_codex_request,
        )
        await runtime.start()
        stack.push_async_callback(runtime.close)

        admission = AdmissionController(
            settings.max_active_operations,
            settings.operation_timeout_seconds,
        )
        agent_service = AgentService(runtime, conversation_repository, admission)

        app.state.approval_service = approval_service
        app.state.codex_runtime = runtime
        app.state.agent_service = agent_service

        try:
            yield
        finally:
            await admission.drain(settings.shutdown_timeout_seconds)
            try:
                await runtime.close()
            finally:
                await admission.cancel_after_runtime_closed()
