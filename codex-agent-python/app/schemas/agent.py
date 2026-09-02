from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateConversationResponse(BaseModel):
    """创建平台业务会话后的响应。"""

    conversation_id: str = Field(description="平台级 Conversation ID")
    agent_id: str
    created_at: datetime


class ConversationReadResponse(BaseModel):
    """读取业务会话对应 Runtime 状态后的响应。"""

    conversation_id: str
    agent_id: str
    runtime: str
    thread: dict[str, Any]


class CompactConversationResponse(BaseModel):
    """触发 Conversation 对应 Runtime Thread Compaction 后的响应。"""

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
