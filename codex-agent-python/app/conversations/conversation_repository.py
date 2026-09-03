from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class Conversation:
    """企业业务会话与具体 Agent Runtime Thread 的映射。"""

    id: str
    agent_id: str
    tenant_id: str
    user_id: str
    runtime_type: str
    runtime_thread_id: str
    runtime_lease_owner: str
    runtime_lease_expires_at: datetime
    runtime_generation: int
    created_at: datetime


metadata = MetaData()

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("agent_id", String(128), nullable=False),
    Column("tenant_id", String(128), nullable=False),
    Column("user_id", String(128), nullable=False),
    Column("runtime_type", String(64), nullable=False),
    Column("runtime_thread_id", String(128), nullable=False, unique=True),
    # 旧字段暂时保留用于向后兼容；新的路由决策只认 lease 字段。
    Column("runtime_instance_id", String(128), nullable=False),
    Column("runtime_lease_owner", String(128), nullable=False),
    Column("runtime_lease_expires_at", DateTime(timezone=True), nullable=False),
    Column("runtime_generation", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class ConversationRepository:
    """PostgreSQL Conversation 仓储。

    外部 API 只使用 conversation_id。Runtime Worker 对会话的归属是有期限 lease，
    不再把某个实例当成永久 owner；实例失联后其他 Worker 可以在 lease 过期后接管。
    """

    def __init__(self, database_url: str) -> None:
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)

    def healthcheck(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT id FROM conversations LIMIT 1"))

    def close(self) -> None:
        self._engine.dispose()

    def create(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        runtime_type: str,
        runtime_thread_id: str,
        runtime_instance_id: str,
        lease_seconds: int,
    ) -> Conversation:
        now = datetime.now(timezone.utc)
        item = Conversation(
            id=conversation_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            runtime_type=runtime_type,
            runtime_thread_id=runtime_thread_id,
            runtime_lease_owner=runtime_instance_id,
            runtime_lease_expires_at=now + timedelta(seconds=lease_seconds),
            runtime_generation=1,
            created_at=now,
        )
        with self._engine.begin() as conn:
            conn.execute(
                insert(conversations).values(
                    id=item.id,
                    agent_id=item.agent_id,
                    tenant_id=item.tenant_id,
                    user_id=item.user_id,
                    runtime_type=item.runtime_type,
                    runtime_thread_id=item.runtime_thread_id,
                    runtime_instance_id=runtime_instance_id,
                    runtime_lease_owner=item.runtime_lease_owner,
                    runtime_lease_expires_at=item.runtime_lease_expires_at,
                    runtime_generation=item.runtime_generation,
                    created_at=item.created_at,
                )
            )
        return item

    def get_owned(self, conversation_id: str, *, tenant_id: str, user_id: str) -> Conversation:
        stmt = select(conversations).where(
            conversations.c.id == conversation_id,
            conversations.c.tenant_id == tenant_id,
            conversations.c.user_id == user_id,
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        if row is None:
            raise KeyError(conversation_id)
        return self._from_row(row)

    def acquire_lease(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
        runtime_instance_id: str,
        lease_seconds: int,
    ) -> Conversation | None:
        """原子续租或接管一个 Conversation。

        只有当前 owner 或已经过期的 lease 可以更新。返回 None 表示仍有其他健康 Worker 持有它。
        """

        now = datetime.now(timezone.utc)
        stmt = (
            update(conversations)
            .where(
                conversations.c.id == conversation_id,
                conversations.c.tenant_id == tenant_id,
                conversations.c.user_id == user_id,
                or_(
                    conversations.c.runtime_lease_owner == runtime_instance_id,
                    conversations.c.runtime_lease_expires_at <= now,
                ),
            )
            .values(
                runtime_lease_owner=runtime_instance_id,
                runtime_lease_expires_at=now + timedelta(seconds=lease_seconds),
                runtime_generation=conversations.c.runtime_generation + 1,
            )
            .returning(*conversations.c)
        )
        with self._engine.begin() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        return self._from_row(row) if row is not None else None

    def find_by_runtime_thread_id(self, runtime_thread_id: str) -> Conversation:
        stmt = select(conversations).where(
            conversations.c.runtime_thread_id == runtime_thread_id
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).mappings().one_or_none()
        if row is None:
            raise KeyError(runtime_thread_id)
        return self._from_row(row)

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _from_row(row) -> Conversation:
        return Conversation(
            id=row["id"],
            agent_id=row["agent_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            runtime_type=row["runtime_type"],
            runtime_thread_id=row["runtime_thread_id"],
            runtime_lease_owner=row["runtime_lease_owner"],
            runtime_lease_expires_at=row["runtime_lease_expires_at"],
            runtime_generation=row["runtime_generation"],
            created_at=row["created_at"],
        )
