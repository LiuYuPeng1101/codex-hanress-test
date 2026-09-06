from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol


@dataclass(frozen=True)
class ExecutionDecision:
    status: str
    approval_id: str
    execution_id: str | None
    expires_at: datetime


class ExecutionStore(Protocol):
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
    ) -> ExecutionDecision: ...


class ConversationOwnership(Protocol):
    def get_owned(self, conversation_id: str, *, user_id: str, tenant_id: str) -> Any: ...


class ExecutionService:
    """An operation registry supplies business validation; grants and IDs stay server-owned."""

    def __init__(
        self,
        store: ExecutionStore,
        conversations: ConversationOwnership,
        operations: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]],
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Execution grant TTL must be positive")
        self._store = store
        self._conversations = conversations
        self._operations = dict(operations)
        self._ttl_seconds = ttl_seconds

    def prepare(
        self,
        *,
        conversation_id: str,
        user_id: str,
        tenant_id: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> ExecutionDecision:
        # Shared service credentials alone do not confer ownership of a conversation.
        self._conversations.get_owned(conversation_id, user_id=user_id, tenant_id=tenant_id)
        validator = self._operations.get(operation)
        if validator is None:
            raise ValueError("UNSUPPORTED_OPERATION")
        validated = validator(arguments)
        canonical = json.dumps(
            {
                "version": 1,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "operation": operation,
                "arguments": validated,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self._store.prepare_execution(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            approval_key=fingerprint,
            operation=operation,
            arguments=validated,
            ttl_seconds=self._ttl_seconds,
        )
