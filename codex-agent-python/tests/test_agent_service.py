from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.conversations.conversation_repository import Conversation
from app.services.agent_service import AgentService, RuntimeLeaseConflict


def _conversation(owner: str = "runtime-01") -> Conversation:
    now = datetime.now(timezone.utc)
    return Conversation(
        id="conversation-1",
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_lease_owner=owner,
        runtime_lease_expires_at=now + timedelta(seconds=30),
        runtime_generation=1,
        created_at=now,
    )


def _service(runtime: Mock, conversations: Mock) -> AgentService:
    return AgentService(
        runtime,
        conversations,
        agent_id="order-agent",
        runtime_instance_id="runtime-01",
        runtime_lease_seconds=30,
    )


@pytest.mark.asyncio
async def test_create_conversation_persists_runtime_mapping() -> None:
    runtime = Mock()
    runtime.create_thread = AsyncMock(return_value="thread-1")
    runtime.archive_thread = AsyncMock()
    conversations = Mock()
    conversations.new_id.return_value = "conversation-1"
    conversations.create.return_value = _conversation()
    service = _service(runtime, conversations)

    created = await service.create_conversation(
        tenant_id="tenant-a",
        user_id="user-1",
        roles=frozenset({"support.agent"}),
    )

    assert created.id == "conversation-1"
    runtime.create_thread.assert_awaited_once_with(
        conversation_id="conversation-1",
        user_id="user-1",
        tenant_id="tenant-a",
        roles=frozenset({"support.agent"}),
    )
    conversations.create.assert_called_once_with(
        conversation_id="conversation-1",
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_instance_id="runtime-01",
        lease_seconds=30,
    )


@pytest.mark.asyncio
async def test_orphan_thread_is_archived_when_mapping_fails() -> None:
    runtime = Mock()
    runtime.create_thread = AsyncMock(return_value="thread-orphan")
    runtime.archive_thread = AsyncMock()
    conversations = Mock()
    conversations.new_id.return_value = "conversation-1"
    conversations.create.side_effect = RuntimeError("db unavailable")
    service = _service(runtime, conversations)

    with pytest.raises(RuntimeError, match="db unavailable"):
        await service.create_conversation(
            tenant_id="tenant-a",
            user_id="user-1",
            roles=frozenset(),
        )

    runtime.archive_thread.assert_awaited_once_with("thread-orphan")


@pytest.mark.asyncio
async def test_unexpired_lease_blocks_second_worker() -> None:
    runtime = Mock()
    runtime.run_turn = AsyncMock()
    conversations = Mock()
    conversations.get_owned.return_value = _conversation(owner="runtime-02")
    conversations.acquire_lease.return_value = None
    service = _service(runtime, conversations)

    with pytest.raises(RuntimeLeaseConflict) as exc_info:
        await service.chat(
            "conversation-1",
            "查询订单",
            tenant_id="tenant-a",
            user_id="user-1",
            roles=frozenset(),
        )

    assert exc_info.value.owner == "runtime-02"
    runtime.run_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_lease_can_be_taken_over_and_current_roles_reinjected() -> None:
    runtime = Mock()
    runtime.run_turn = AsyncMock(return_value="ok")
    conversations = Mock()
    conversations.get_owned.return_value = _conversation(owner="runtime-02")
    conversations.acquire_lease.return_value = _conversation(owner="runtime-01")
    service = _service(runtime, conversations)

    result = await service.chat(
        "conversation-1",
        "查询订单",
        tenant_id="tenant-a",
        user_id="user-1",
        roles=frozenset({"support.agent", "order.read"}),
    )

    assert result == "ok"
    runtime.run_turn.assert_awaited_once_with(
        "thread-1",
        "conversation-1",
        "查询订单",
        user_id="user-1",
        tenant_id="tenant-a",
        roles=frozenset({"support.agent", "order.read"}),
    )
