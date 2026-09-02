from datetime import datetime

from pydantic import BaseModel


class ApprovalResponse(BaseModel):
    """企业审批页面使用的安全字段。

    Codex 原始 params、runtime thread/turn ID 只保存在数据库与受控审计链路中，
    不作为普通审批 API 的对外契约。
    """

    id: str
    conversation_id: str
    requester_user_id: str
    tenant_id: str
    server_name: str | None
    message: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    decision: str | None
    decided_by: str | None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalResponse]
