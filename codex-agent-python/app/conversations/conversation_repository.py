from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

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
)
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class Conversation:
    """业务会话与 Codex Thread 的持久化映射。"""

    id: str
    tenant_id: str
    user_id: str
    runtime_thread_id: str
    created_at: datetime


metadata = MetaData()

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("user_id", String(128), nullable=False),
    Column("runtime_thread_id", String(128), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class ConversationRepository:
    """单 Agent 的 Conversation 仓储。

    这里只解决业务 conversation_id 与 Codex thread_id 的映射和所有权校验；
    不承担多 Runtime 路由、Lease、Scheduler 或 Agent Registry 职责。
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
        tenant_id: str,
        user_id: str,
        runtime_thread_id: str,
    ) -> Conversation:
        item = Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            runtime_thread_id=runtime_thread_id,
            created_at=datetime.now(timezone.utc),
        )
        with self._engine.begin() as conn:
            conn.execute(
                insert(conversations).values(
                    id=item.id,
                    tenant_id=item.tenant_id,
                    user_id=item.user_id,
                    runtime_thread_id=item.runtime_thread_id,
                    created_at=item.created_at,
                )
            )
        return item

    def get_owned(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Conversation:
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
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            runtime_thread_id=row["runtime_thread_id"],
            created_at=row["created_at"],
        )
