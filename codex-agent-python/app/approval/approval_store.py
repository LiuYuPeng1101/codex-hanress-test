from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ApprovalRequest:
    """一条等待人工处理的审批请求。

    当前学习项目先把审批状态保存在内存中。生产环境通常会换成数据库或 Redis，
    这样即使 Agent Service 重启、扩容到多个实例，审批状态也不会丢失。
    """

    id: str
    method: str
    params: dict[str, Any]
    status: str = "PENDING"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None
    decision: str | None = None
    _event: threading.Event = field(default_factory=threading.Event, repr=False)


class ApprovalStore:
    """内存版 Approval Center。

    Codex App Server 的 Server Request 由 SDK 的后台 reader thread 处理。
    当收到需要人工确认的 MCP Tool Approval 时，该线程会调用 wait_for_decision() 阻塞等待；
    FastAPI 自己的事件循环不会被这个 threading.Event 阻塞，因此审批 API 仍可正常访问。
    """

    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()

    def create(self, method: str, params: dict[str, Any]) -> ApprovalRequest:
        """创建一条待审批记录。"""

        item = ApprovalRequest(
            id=str(uuid.uuid4()),
            method=method,
            params=params,
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def list_all(self) -> list[ApprovalRequest]:
        """按创建时间倒序返回全部审批记录。"""

        with self._lock:
            return sorted(self._items.values(), key=lambda item: item.created_at, reverse=True)

    def get(self, approval_id: str) -> ApprovalRequest:
        """根据 ID 获取审批记录。"""

        with self._lock:
            item = self._items.get(approval_id)
        if item is None:
            raise KeyError(approval_id)
        return item

    def decide(self, approval_id: str, decision: str) -> ApprovalRequest:
        """写入人工决策并唤醒正在等待的 Codex approval handler。"""

        if decision not in {"approve", "reject"}:
            raise ValueError("decision 只能是 approve 或 reject")

        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                raise KeyError(approval_id)
            if item.status != "PENDING":
                raise ValueError("该审批已经处理，不能重复审批")

            item.decision = decision
            item.status = "APPROVED" if decision == "approve" else "REJECTED"
            item.decided_at = datetime.now(timezone.utc)
            item._event.set()
            return item

    def wait_for_decision(self, approval_id: str) -> str:
        """阻塞等待人工审批，并返回 approve / reject。

        注意：这个方法运行在 Codex SDK 的同步后台线程中，不运行在 FastAPI event loop 中。
        因此这里使用 threading.Event 是合适的；生产环境则通常改成持久化状态 + 消息通知。
        """

        item = self.get(approval_id)
        item._event.wait()
        assert item.decision is not None
        return item.decision
