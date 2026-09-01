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
    """

    settings = get_settings()
    runtime = CodexRuntime(settings.agent_workspace)
    await runtime.start()

    app.state.codex_runtime = runtime
    app.state.agent_service = AgentService(runtime)

    try:
        yield
    finally:
        await runtime.close()
