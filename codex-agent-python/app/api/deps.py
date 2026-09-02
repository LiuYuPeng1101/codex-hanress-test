from fastapi import Request

from app.approval.approval_service import ApprovalService
from app.services.agent_service import AgentService


def get_agent_service(request: Request) -> AgentService:
    """从 FastAPI application state 中取得 AgentService。"""

    return request.app.state.agent_service


def get_approval_service(request: Request) -> ApprovalService:
    """从 FastAPI application state 中取得 ApprovalService。

    API 层只依赖 ApprovalService，不直接访问内存 Store；以后把 Store 换成数据库时，
    Controller 不需要跟着修改。
    """

    return request.app.state.approval_service
