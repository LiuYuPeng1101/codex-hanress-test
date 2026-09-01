from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.runtime.codex_runtime import CodexRuntime
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理 FastAPI 应用生命周期。

    应用启动时创建并启动一份 CodexRuntime；应用关闭时统一释放。
    这样不会在每个 HTTP 请求里重复启动 Codex 底层进程。

    Runtime 创建时同时注入 Java 业务系统的订单 MCP Server 地址，
    后续所有 Thread / Turn 都复用同一套 Codex Runtime 配置。
    """

    settings = get_settings()
    runtime = CodexRuntime(
        workspace=settings.agent_workspace,
        order_mcp_url=settings.order_mcp_url,
    )
    await runtime.start()

    app.state.codex_runtime = runtime
    app.state.agent_service = AgentService(runtime)

    try:
        yield
    finally:
        await runtime.close()
