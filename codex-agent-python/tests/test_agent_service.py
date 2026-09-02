from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.conversations.conversation_repository import Conversation
from app.services.agent_service import AgentService, RuntimeOwnershipError


def _conversation(instance_id: str = "runtime-01") -> Conversation:
    return Conversation(
        id="conversation-1",
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_instance_id=instance_id,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_conversation_persists_runtime_mapping() -> None:
    runtime = Mock()
    runtime.create_thread = AsyncMock(return_value="thread-1")
    runtime.archive_thread = AsyncMock()
    conversations = Mock()
    conversations.create.return_value = _conversation()
    service = AgentService(
        runtime,
        conversations,
        agent_id="order-agent",
        runtime_instance_id="runtime-01",
    )

    created = await service.create_conversation(
        tenant_id="tenant-a",
        user_id="user-1",
        roles=frozenset({"support.agent"}),
    )

    assert created.id == "conversation-1"
    runtime.create_thread.assert_awaited_once_with(
        user_id="user-1",
        tenant_id="tenant-a",
        roles=frozenset({"support.agent"}),
    )
    conversations.create.assert_called_once_with(
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_instance_id="runtime-01",
    )


@pytest.mark.asyncio
async def test_orphan_thread_is_archived_when_mapping_fails() -> None:
    runtime = Mock()
    runtime.create_thread = AsyncMock(return_value="thread-orphan")
    runtime.archive_thread = AsyncMock()
    conversations = Mock()
    conversations.create.side_effect = RuntimeError("db unavailable")
    service = AgentService(
        runtime,
        conversations,
        agent_id="order-agent",
        runtime_instance_id="runtime-01",
    )

    with pytest.raises(RuntimeError, match="db unavailable"):
        await service.create_conversation(
            tenant_id="tenant-a",
            user_id="user-1",
            roles=frozenset(),
        )

    runtime.archive_thread.assert_awaited_once_with("thread-orphan")


@pytest.mark.asyncio
async def test_wrong_runtime_instance_requires_sticky_routing() -> None:
    runtime = Mock()
    runtime.run_turn = AsyncMock()
    conversations = Mock()
    conversations.get_owned.return_value = _conversation(instance_id="runtime-02")
    service = AgentService(
        runtime,
        conversations,
        agent_id="order-agent",
        runtime_instance_id="runtime-01",
    )

    with pytest.raises(RuntimeOwnershipError) as exc_info:
        await service.chat(
            "conversation-1",
            "查询订单",
            tenant_id="tenant-a",
            user_id="user-1",
            roles=frozenset(),
        )

    assert exc_info.value.expected_instance_id == "runtime-02"
    runtime.run_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_roles_are_reinjected_on_each_turn() -> None:
    runtime = Mock()
    runtime.run_turn = AsyncMock(return_value="ok")
    conversations = Mock()
    conversations.get_owned.return_value = _conversation()
    service = AgentService(
        runtime,
        conversations,
        agent_id="order-agent",
        runtime_instance_id="runtime-01",
    )

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
