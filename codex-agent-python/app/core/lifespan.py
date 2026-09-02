from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.approval.approval_service import ApprovalService
from app.approval.approval_store import ApprovalStore
from app.core.config import get_settings
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理 FastAPI 应用生命周期。

    应用启动时创建 ApprovalStore / ApprovalService / CodexRuntime；
    Codex Runtime 收到需要人工确认的 MCP Tool Approval 后，会通过 ApprovalService
    创建待审批记录并等待 API 层的 approve / reject 操作。
    """

    settings = get_settings()

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
