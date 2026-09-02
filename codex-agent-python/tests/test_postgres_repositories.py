import os
import uuid

import pytest

from app.approval.approval_repository import ApprovalRepository
from app.conversations.conversation_repository import ConversationRepository


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL 未配置")
    return value


def test_conversation_and_approval_tenant_isolation() -> None:
    database_url = _database_url()
    conversations = ConversationRepository(database_url)
    approvals = ApprovalRepository(database_url, poll_interval_seconds=0.01)

    runtime_thread_id = f"thread-{uuid.uuid4()}"
    conversation = conversations.create(
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id=runtime_thread_id,
        runtime_instance_id="runtime-01",
    )

    assert conversations.get_owned(
        conversation.id,
        tenant_id="tenant-a",
        user_id="user-1",
    ).runtime_thread_id == runtime_thread_id

    with pytest.raises(KeyError):
        conversations.get_owned(
            conversation.id,
            tenant_id="tenant-b",
            user_id="user-1",
        )

    approval = approvals.create(
        "mcpServer/elicitation/request",
        {
            "threadId": runtime_thread_id,
            "turnId": "turn-1",
            "serverName": "order",
            "meta": {"codex_approval_kind": "mcp_tool_call"},
        },
        conversation_id=conversation.id,
        requester_user_id="user-1",
        tenant_id="tenant-a",
    )

    assert [item.id for item in approvals.list_for_tenant("tenant-a")] == [approval.id]
    assert approvals.list_for_tenant("tenant-b") == []

    with pytest.raises(KeyError):
        approvals.decide(
            approval.id,
            "approve",
            decided_by="approver-b",
            tenant_id="tenant-b",
        )

    approved = approvals.decide(
        approval.id,
        "approve",
        decided_by="approver-a",
        tenant_id="tenant-a",
    )
    assert approved.status == "APPROVED"
    assert approved.decided_by == "approver-a"

    with pytest.raises(ValueError):
        approvals.decide(
            approval.id,
            "approve",
            decided_by="approver-a",
            tenant_id="tenant-a",
        )

    approvals.close()
    conversations.close()
