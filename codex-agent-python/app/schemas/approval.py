from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ApprovalResponse(BaseModel):
    """企业审批记录响应。"""

    id: str
    conversation_id: str
    requester_user_id: str
    tenant_id: str
    method: str
    runtime_thread_id: str | None
    runtime_turn_id: str | None
    server_name: str | None
    params: dict[str, Any]
    status: str
    created_at: datetime
    decided_at: datetime | None
    decision: str | None
    decided_by: str | None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalResponse]
