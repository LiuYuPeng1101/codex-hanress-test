from typing import Any

from pydantic import BaseModel, Field


class CreateThreadResponse(BaseModel):
    """创建 Agent 会话后的响应。"""

    thread_id: str = Field(description="Codex Thread ID")


class ThreadReadResponse(BaseModel):
    """读取 Thread 快照后的响应。"""

    thread: dict[str, Any]


class CompactThreadResponse(BaseModel):
    """触发 Thread Compaction 后的响应。"""

    thread_id: str
    status: str


class RunTurnRequest(BaseModel):
    """执行一轮 Agent 对话的请求。"""

    message: str = Field(min_length=1, description="用户输入")


class RunTurnResponse(BaseModel):
    """执行一轮 Agent 对话后的响应。"""

    thread_id: str
    answer: str


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    service: str
