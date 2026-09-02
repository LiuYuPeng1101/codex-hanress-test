from typing import Any

from pydantic import BaseModel, Field


class CreateConversationResponse(BaseModel):
    """创建企业 Agent 会话后的响应。"""

    conversation_id: str = Field(description="企业业务 Conversation ID")


class ConversationReadResponse(BaseModel):
    """读取会话诊断快照后的响应。

    `runtime_snapshot` 仅用于受控运维诊断，外部事件和业务 API 不依赖其中的 Codex 字段。
    """

    conversation_id: str
    runtime_snapshot: dict[str, Any]


class CompactConversationResponse(BaseModel):
    conversation_id: str
    status: str


class RunTurnRequest(BaseModel):
    message: str = Field(min_length=1, description="用户输入")


class RunTurnResponse(BaseModel):
    conversation_id: str
    answer: str


class HealthResponse(BaseModel):
    status: str
    service: str
