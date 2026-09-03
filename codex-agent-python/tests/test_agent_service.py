from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.conversations.conversation_repository import Conversation
from app.services.agent_service import AgentService


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-1",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_thread_id="thread-1",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_conversation_persists_codex_thread_mapping() -> None:
    runtime = Mock()
    runtime.create_thread = AsyncMock(return_value="thread-1")
    runtime.archive_thread = AsyncMock()
    conversations = Mock()
    conversations.new_id.return_value = "conversation-1"
    conversations.create.return_value = _conversation()
    service = AgentService(runtime, conversations)

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
        conversation_id="conversation-1",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_thread_id="thread-1",
    )


@pytest.mark.asyncio
async def test_chat_resumes_mapped_codex_thread() -> None:
    runtime = Mock()
    runtime.run_turn = AsyncMock(return_value="ok")
    conversations = Mock()
    conversations.get_owned.return_value = _conversation()
    service = AgentService(runtime, conversations)

    result = await service.chat(
        "conversation-1",
        "查询订单",
        tenant_id="tenant-a",
        user_id="user-1",
        roles=frozenset({"order.read"}),
    )

    assert result == "ok"
    runtime.run_turn.assert_awaited_once_with(
        "thread-1",
        "conversation-1",
        "查询订单",
        user_id="user-1",
        tenant_id="tenant-a",
        roles=frozenset({"order.read"}),
    )
