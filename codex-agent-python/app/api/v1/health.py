from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.agent import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """服务健康检查。

    当前只表示 FastAPI 进程可响应；后续可以继续增加 Codex Runtime readiness 检查。
    """

    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name)
