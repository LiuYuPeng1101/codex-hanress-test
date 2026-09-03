from __future__ import annotations

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
from sqlalchemy.exc import IntegrityError


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """持久化审批记录，同时也是一次性高风险动作授权。"""

    id: str
    approval_key: str
    conversation_id: str
    requester_user_id: str
    tenant_id: str
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
    consumed_at: datetime | None


metadata = MetaData()

approval_requests = Table(
    "approval_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("approval_key", String(64), nullable=False),
    Column("conversation_id", String(36), nullable=False),
    Column("requester_user_id", String(128), nullable=False),
    Column("tenant_id", String(128), nullable=False),
    Column("method", String(128), nullable=False),
    Column("thread_id", String(128), nullable=True),
    Column("turn_id", String(128), nullable=True),
    Column("server_name", String(128), nullable=True),
    Column("params", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
    Column("decision", String(32), nullable=True),
    Column("decided_by", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
)


class ApprovalRepository:
    """基于 PostgreSQL 的多租户审批仓储。

    Human Approval 不依赖某个 Python 进程内的等待对象。APPROVED 是一个持久化的一次性 grant；
    下次完全相同的高风险动作请求到达时，Runtime 原子消费它并继续执行。
    """

    def __init__(self, database_url: str) -> None:
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)

    def healthcheck(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT id FROM approval_requests LIMIT 1"))

    def close(self) -> None:
        self._engine.dispose()

    def create_pending(
        self,
        method: str,
        params: dict[str, Any],
        *,
        approval_key: str,
        conversation_id: str,
        requester_user_id: str,
        tenant_id: str,
    ) -> ApprovalRequest:
        now = datetime.now(timezone.utc)
        item = ApprovalRequest(
            id=str(uuid.uuid4()),
            approval_key=approval_key,
            conversation_id=conversation_id,
            requester_user_id=requester_user_id,
            tenant_id=tenant_id,
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
            consumed_at=None,
        )
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(approval_requests).values(
                        id=item.id,
                        approval_key=item.approval_key,
                        conversation_id=item.conversation_id,
                        requester_user_id=item.requester_user_id,
                        tenant_id=item.tenant_id,
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
        except IntegrityError:
            existing = self.find_actionable(conversation_id, approval_key)
            if existing is None:
                raise
            return existing

    def find_actionable(self, conversation_id: str, approval_key: str) -> ApprovalRequest | None:
        """查找同一业务动作当前尚未结束的 PENDING / APPROVED grant。"""

        stmt = (
            select(approval_requests)
            .where(
                approval_requests.c.conversation_id == conversation_id,
                approval_requests.c.approval_key == approval_key,
                approval_requests.c.status.in_(("PENDING", "APPROVED")),
            )
            .order_by(approval_requests.c.created_at.desc())
            .limit(1)
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        return self._from_row(row) if row is not None else None

    def consume_approved_grant(self, approval_id: str) -> ApprovalRequest | None:
        """一次性消费人工批准；并发重试最多只有一个请求能成功。"""

        now = datetime.now(timezone.utc)
        stmt = (
            update(approval_requests)
            .where(
                approval_requests.c.id == approval_id,
                approval_requests.c.status == "APPROVED",
            )
            .values(status="CONSUMED", consumed_at=now)
            .returning(*approval_requests.c)
        )
        with self._engine.begin() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        return self._from_row(row) if row is not None else None

    def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[ApprovalRequest]:
        stmt = (
            select(approval_requests)
            .where(approval_requests.c.tenant_id == tenant_id)
            .order_by(approval_requests.c.created_at.desc())
            .limit(limit)
        )
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
        tenant_id: str,
    ) -> ApprovalRequest:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision 只能是 approve 或 reject")

        now = datetime.now(timezone.utc)
        new_status = "APPROVED" if decision == "approve" else "REJECTED"
        stmt = (
            update(approval_requests)
            .where(
                approval_requests.c.id == approval_id,
                approval_requests.c.tenant_id == tenant_id,
                approval_requests.c.status == "PENDING",
            )
            .values(
                status=new_status,
                decision=decision,
                decided_by=decided_by,
                decided_at=now,
            )
        )
        with self._engine.begin() as conn:
            result = conn.execute(stmt)

        if result.rowcount == 0:
            existing = self.get(approval_id)
            if existing.tenant_id != tenant_id:
                raise KeyError(approval_id)
            if existing.status != "PENDING":
                raise ValueError("该审批已经处理，不能重复审批")
            raise RuntimeError("审批状态更新失败")
        return self.get(approval_id)

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
            approval_key=row["approval_key"],
            conversation_id=row["conversation_id"],
            requester_user_id=row["requester_user_id"],
            tenant_id=row["tenant_id"],
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
            consumed_at=row["consumed_at"],
        )
