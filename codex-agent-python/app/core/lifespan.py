from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.approval.approval_repository import ApprovalRepository
from app.approval.approval_service import ApprovalService
from app.core.config import get_settings
from app.observability.tracing import configure_tracing
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """创建并释放生产运行依赖。任何关键依赖不可用时直接启动失败。"""

    settings = get_settings()
    configure_tracing(
        service_name=settings.app_name,
        otlp_endpoint=settings.otel_exporter_otlp_traces_endpoint,
    )

    approval_repository = ApprovalRepository(settings.database_url)
    approval_repository.healthcheck()
    approval_service = ApprovalService(
        approval_repository,
        timeout_seconds=settings.approval_timeout_seconds,
    )

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
        approval_repository.close()
