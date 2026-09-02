from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AgentEvent:
    """对外暴露的标准化 Agent 事件。

    不直接把 Codex 原始 Notification 原样透传给前端，避免把 reasoning、
    Tool 完整参数或其他内部协议细节泄露出去。前端只依赖这一层稳定事件模型。
    """

    type: str
    thread_id: str
    turn_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""

        return {
            "type": self.type,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }
