from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from redis import Redis


@dataclass(frozen=True, slots=True)
class Conversation:
    """平台层业务会话。

    conversation_id 是稳定的业务标识；runtime_thread_id 是 Codex 专属标识，不能泄漏为
    平台主键。未来切换 Runtime 时只需要替换映射，不影响业务 API。
    """

    id: str
    agent_id: str
    runtime: str
    runtime_thread_id: str
    created_at: datetime


class ConversationRepository:
    """基于 Redis 的 Conversation Repository。"""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def create(self, *, agent_id: str, runtime: str, runtime_thread_id: str) -> Conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            runtime=runtime,
            runtime_thread_id=runtime_thread_id,
            created_at=datetime.now(timezone.utc),
        )
        self._redis.hset(
            self._key(conversation.id),
            mapping={
                "id": conversation.id,
                "agent_id": conversation.agent_id,
                "runtime": conversation.runtime,
                "runtime_thread_id": conversation.runtime_thread_id,
                "created_at": conversation.created_at.isoformat(),
            },
        )
        return conversation

    def get(self, conversation_id: str) -> Conversation:
        payload = self._redis.hgetall(self._key(conversation_id))
        if not payload:
            raise KeyError(conversation_id)
        decoded = {self._decode(k): self._decode(v) for k, v in payload.items()}
        return Conversation(
            id=decoded["id"],
            agent_id=decoded["agent_id"],
            runtime=decoded["runtime"],
            runtime_thread_id=decoded["runtime_thread_id"],
            created_at=datetime.fromisoformat(decoded["created_at"]),
        )

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"agent:conversation:{conversation_id}"

    @staticmethod
    def _decode(value: bytes | str) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value
