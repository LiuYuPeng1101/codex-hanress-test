from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AgentEvent:
    """对外暴露的稳定 Agent 事件。

    不包含 Codex runtime_thread_id / turn_id 等 Runtime 私有标识。前端只依赖业务
    conversation_id 和标准化事件类型，避免被具体 Runtime 协议锁定。
    """

    type: str
    conversation_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "conversation_id": self.conversation_id,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }
