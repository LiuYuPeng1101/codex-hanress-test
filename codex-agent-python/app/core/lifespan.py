from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.definition import AgentDefinition, McpServerDefinition, SandboxPolicy
from app.approval.approval_repository import ApprovalRepository
from app.approval.approval_service import ApprovalService
from app.conversations.conversation_repository import ConversationRepository
from app.core.config import get_settings
from app.observability.tracing import configure_tracing
from app.runtime.codex_runtime import CodexRuntime
from app.security.runtime_identity import RuntimeIdentityIssuer
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """装配并释放生产运行依赖。"""

    settings = get_settings()
    configure_tracing(
        service_name=settings.app_name,
        otlp_endpoint=settings.otel_exporter_otlp_traces_endpoint,
    )

    conversation_repository = ConversationRepository(settings.database_url)
    approval_repository = ApprovalRepository(settings.database_url)
    conversation_repository.healthcheck()
    approval_repository.healthcheck()

    approval_service = ApprovalService(
        approval_repository,
        conversation_repository,
        timeout_seconds=settings.approval_timeout_seconds,
    )

    runtime_identity_issuer = RuntimeIdentityIssuer(
        private_key_path=settings.runtime_identity_private_key_path,
        key_id=settings.runtime_identity_key_id,
        issuer=settings.runtime_identity_issuer,
        audience=settings.runtime_identity_audience,
        ttl_seconds=settings.runtime_identity_ttl_seconds,
    )

    definition = AgentDefinition(
        agent_id=settings.agent_id,
        workspace=str(settings.agent_workspace),
        sandbox=SandboxPolicy.READ_ONLY,
        mcp_servers=(
            McpServerDefinition(
                name="order",
                url=settings.agentgateway_order_mcp_url,
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
        runtime_identity_issuer=runtime_identity_issuer,
    )
    await runtime.start()

    agent_service = AgentService(
        runtime,
        conversation_repository,
        agent_id=definition.agent_id,
        runtime_instance_id=settings.runtime_instance_id,
        runtime_lease_seconds=settings.runtime_lease_seconds,
    )

    app.state.approval_service = approval_service
    app.state.codex_runtime = runtime
    app.state.agent_service = agent_service

    try:
        yield
    finally:
        await runtime.close()
        approval_repository.close()
        conversation_repository.close()
