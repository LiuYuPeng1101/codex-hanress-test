from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ApprovalResponse(BaseModel):
    """审批记录响应。"""

    id: str
    method: str
    thread_id: str | None
    turn_id: str | None
    server_name: str | None
    params: dict[str, Any]
    status: str
    created_at: datetime
    decided_at: datetime | None
    decision: str | None


class ApprovalListResponse(BaseModel):
    """待审批/历史审批列表。"""

    items: list[ApprovalResponse]
