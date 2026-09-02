from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.approval.approval_service import ApprovalService
from app.approval.approval_store import ApprovalStore
from app.core.config import get_settings
from app.observability.tracing import configure_tracing
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理 FastAPI 应用生命周期。

    应用启动时创建 ApprovalStore / ApprovalService / CodexRuntime；
    Codex Runtime 收到需要人工确认的 MCP Tool Approval 后，会通过 ApprovalService
    创建待审批记录并等待 API 层的 approve / reject 操作。

    如果配置了 OTLP Trace Endpoint，还会在启动阶段安装 OpenTelemetry exporter，
    把 Agent Turn / Event Trace 发送到外部 Observability 平台。
    """

    settings = get_settings()

    configure_tracing(
        service_name=settings.app_name,
        otlp_endpoint=settings.otel_exporter_otlp_traces_endpoint,
    )

    approval_store = ApprovalStore()
    approval_service = ApprovalService(approval_store)

    runtime = CodexRuntime(
        workspace=settings.agent_workspace,
        order_mcp_url=settings.order_mcp_url,
        approval_handler=approval_service.handle_codex_request,
    )
    await runtime.start()

    app.state.approval_service = approval_service
    app.state.codex_runtime = runtime
    app.state.agent_service = AgentService(runtime)

    try:
        yield
    finally:
        await runtime.close()
