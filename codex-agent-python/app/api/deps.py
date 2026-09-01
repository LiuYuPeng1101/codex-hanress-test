from fastapi import Request

from app.services.agent_service import AgentService


def get_agent_service(request: Request) -> AgentService:
    """从 FastAPI application state 中取得 AgentService。

    类似 Spring Boot 从容器里注入 Service，只是 FastAPI 常用 Depends 完成依赖注入。
    """

    return request.app.state.agent_service
