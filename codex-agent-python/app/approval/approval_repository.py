from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """持久化审批记录的领域对象。"""

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
    decided_by: str | None
    decided_tenant_id: str | None


class ApprovalTimeoutError(TimeoutError):
    """审批在规定时间内没有得到人工决策。"""


metadata = MetaData()

approval_requests = Table(
    "approval_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("method", String(128), nullable=False),
    Column("thread_id", String(128), nullable=True),
    Column("turn_id", String(128), nullable=True),
    Column("server_name", String(128), nullable=True),
    Column("params", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
    Column("decision", String(32), nullable=True),
    Column("decided_by", String(128), nullable=True),
    Column("decided_tenant_id", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
)


class ApprovalRepository:
    """基于 PostgreSQL 的审批仓储。

    仓储不在应用启动时自动建表。生产环境应通过数据库迁移先创建表，应用只验证连接和使用数据。
    决策更新带 `status=PENDING` 条件，保证多个 Agent Service 实例同时处理时只有一个实例能成功落库。
    """

    def __init__(self, database_url: str, poll_interval_seconds: float = 0.5) -> None:
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)
        self._poll_interval_seconds = poll_interval_seconds

    def healthcheck(self) -> None:
        """验证数据库连接以及审批表是否已经完成迁移。"""

        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT id FROM approval_requests LIMIT 1"))

    def close(self) -> None:
        self._engine.dispose()

    def create(self, method: str, params: dict[str, Any]) -> ApprovalRequest:
        now = datetime.now(timezone.utc)
        item = ApprovalRequest(
            id=str(uuid.uuid4()),
            method=method,
            thread_id=self._optional_text(params, "threadId", "thread_id"),
            turn_id=self._optional_text(params, "turnId", "turn_id"),
            server_name=self._optional_text(params, "serverName", "server_name"),
            params=params,
            status="PENDING",
            created_at=now,
            decided_at=None,
            decision=None,
            decided_by=None,
            decided_tenant_id=None,
        )
        with self._engine.begin() as conn:
            conn.execute(
                insert(approval_requests).values(
                    id=item.id,
                    method=item.method,
                    thread_id=item.thread_id,
                    turn_id=item.turn_id,
                    server_name=item.server_name,
                    params=item.params,
                    status=item.status,
                    created_at=item.created_at,
                )
            )
        return item

    def list_all(self, limit: int = 100) -> list[ApprovalRequest]:
        stmt = select(approval_requests).order_by(approval_requests.c.created_at.desc()).limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._from_row(row) for row in rows]

    def get(self, approval_id: str) -> ApprovalRequest:
        stmt = select(approval_requests).where(approval_requests.c.id == approval_id)
        with self._engine.connect() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        if row is None:
            raise KeyError(approval_id)
        return self._from_row(row)

    def decide(
        self,
        approval_id: str,
        decision: str,
        *,
        decided_by: str,
        decided_tenant_id: str,
    ) -> ApprovalRequest:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision 只能是 approve 或 reject")

        now = datetime.now(timezone.utc)
        new_status = "APPROVED" if decision == "approve" else "REJECTED"
        stmt = (
            update(approval_requests)
            .where(
                approval_requests.c.id == approval_id,
                approval_requests.c.status == "PENDING",
            )
            .values(
                status=new_status,
                decision=decision,
                decided_by=decided_by,
                decided_tenant_id=decided_tenant_id,
                decided_at=now,
            )
        )
        with self._engine.begin() as conn:
            result = conn.execute(stmt)

        if result.rowcount == 0:
            existing = self.get(approval_id)
            if existing.status != "PENDING":
                raise ValueError("该审批已经处理，不能重复审批")
            raise RuntimeError("审批状态更新失败")
        return self.get(approval_id)

    def wait_for_decision(self, approval_id: str, timeout_seconds: int) -> str:
        """等待跨实例可见的人工决策。

        当前使用数据库轮询，是为了保持 Codex 同步 approval handler 的协议语义，同时避免进程内 Event。
        后续在高吞吐部署中可以把唤醒机制替换为 PostgreSQL LISTEN/NOTIFY、Redis Pub/Sub 或消息队列，
        但审批记录本身仍应由持久化存储作为事实来源。
        """

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            item = self.get(approval_id)
            if item.status == "APPROVED":
                return "approve"
            if item.status in {"REJECTED", "EXPIRED"}:
                return "reject"
            time.sleep(self._poll_interval_seconds)

        self._expire_if_pending(approval_id)
        raise ApprovalTimeoutError(f"审批 {approval_id} 等待超时")

    def _expire_if_pending(self, approval_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(approval_requests)
                .where(
                    approval_requests.c.id == approval_id,
                    approval_requests.c.status == "PENDING",
                )
                .values(
                    status="EXPIRED",
                    decision="reject",
                    decided_at=datetime.now(timezone.utc),
                )
            )

    @staticmethod
    def _optional_text(params: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _from_row(row: Any) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            method=row["method"],
            thread_id=row["thread_id"],
            turn_id=row["turn_id"],
            server_name=row["server_name"],
            params=dict(row["params"]),
            status=row["status"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decision=row["decision"],
            decided_by=row["decided_by"],
            decided_tenant_id=row["decided_tenant_id"],
        )
