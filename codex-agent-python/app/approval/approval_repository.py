from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.executions.service import ExecutionDecision


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """持久化审批及执行 ID；CONSUMED 只表示已签发，不能解释为业务成功。"""

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
    execution_id: str | None = None
    operation: str | None = None
    operation_arguments: dict[str, Any] | None = None
    expires_at: datetime | None = None


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
    Column("execution_id", String(36)),
    Column("operation", String(128)),
    Column("operation_arguments", JSONB),
    Column("expires_at", DateTime(timezone=True)),
)


class ApprovalRepository:
    """PostgreSQL 是审批与执行 ID 的事实源；业务提交状态仍由 OMS 拥有。

    新授权由 prepare_execution 原子签发并稳定重放。旧 SDK grant 方法仅保留历史兼容，
    当前 Runtime callback 不再创建或消费它们。
    """

    def __init__(self, database_url: str) -> None:
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)

    def healthcheck(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(
                text(
                    "SELECT id, execution_id, operation, operation_arguments, expires_at "
                    "FROM approval_requests LIMIT 1"
                )
            )

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

    def prepare_execution(
        self,
        *,
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        approval_key: str,
        operation: str,
        arguments: dict[str, Any],
        ttl_seconds: int,
    ) -> ExecutionDecision:
        """Create/check a grant and reserve its execution ID in one PostgreSQL transaction.

        CONSUMED means an ID was issued, not that OMS committed the operation. Replays
        return the same ID; no local success cache pretends to own OMS state.
        """
        with self._engine.begin() as conn:
            # Database time is the authority for grant expiry across service instances.
            now = conn.execute(select(func.clock_timestamp())).scalar_one()
            conn.execute(
                pg_insert(approval_requests)
                .values(
                    id=str(uuid.uuid4()),
                    execution_id=str(uuid.uuid4()),
                    approval_key=approval_key,
                    conversation_id=conversation_id,
                    requester_user_id=user_id,
                    tenant_id=tenant_id,
                    method="business/execution",
                    server_name=None,
                    params={
                        "message": f"{operation}: " + json.dumps(arguments, ensure_ascii=False)
                    },
                    operation=operation,
                    operation_arguments=arguments,
                    status="PENDING",
                    created_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
                .on_conflict_do_nothing()
            )
            row = (
                conn.execute(
                    select(approval_requests)
                    .where(
                        approval_requests.c.conversation_id == conversation_id,
                        approval_requests.c.approval_key == approval_key,
                        approval_requests.c.execution_id.is_not(None),
                        approval_requests.c.tenant_id == tenant_id,
                        approval_requests.c.requester_user_id == user_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            now = conn.execute(select(func.clock_timestamp())).scalar_one()
            if row["expires_at"] <= now:
                status = "EXPIRED"
            elif row["status"] == "APPROVED":
                conn.execute(
                    update(approval_requests)
                    .where(
                        approval_requests.c.id == row["id"],
                    )
                    .values(status="CONSUMED", consumed_at=now)
                )
                status = "AUTHORIZED"
            elif row["status"] == "CONSUMED":
                status = "AUTHORIZED"
            else:
                status = row["status"]
            return ExecutionDecision(
                status=status,
                approval_id=row["id"],
                execution_id=row["execution_id"] if status == "AUTHORIZED" else None,
                expires_at=row["expires_at"],
            )

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
                approval_requests.c.execution_id.is_(None),
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
                or_(
                    approval_requests.c.expires_at.is_(None),
                    approval_requests.c.expires_at > func.clock_timestamp(),
                ),
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
            if existing.expires_at and existing.expires_at <= datetime.now(timezone.utc):
                raise ValueError("审批已过期，不能执行")
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
            execution_id=row["execution_id"],
            operation=row["operation"],
            operation_arguments=row["operation_arguments"],
            expires_at=row["expires_at"],
        )
