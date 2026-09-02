from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis import Redis

from app.agents.definitions import build_order_agent
from app.approval.approval_service import ApprovalService
from app.approval.approval_store import ApprovalStore
from app.core.config import get_settings
from app.observability.tracing import configure_tracing
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """创建并释放 Agent Service 的生产依赖。"""

    settings = get_settings()
    configure_tracing(
        service_name=settings.app_name,
        otlp_endpoint=settings.otel_exporter_otlp_traces_endpoint,
    )

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    redis.ping()

    approval_store = ApprovalStore(
        redis,
        wait_timeout_seconds=settings.approval_wait_timeout_seconds,
    )
    approval_service = ApprovalService(approval_store)

    definition = build_order_agent(
        workspace=settings.agent_workspace,
        order_mcp_url=settings.order_mcp_url,
    )
    runtime = CodexRuntime(
        definition=definition,
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
        redis.close()
