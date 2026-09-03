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


def test_conversation_mapping_and_approval_isolation() -> None:
    database_url = _database_url()
    conversations = ConversationRepository(database_url)
    approvals = ApprovalRepository(database_url)

    runtime_thread_id = f"thread-{uuid.uuid4()}"
    conversation = conversations.create(
        conversation_id=str(uuid.uuid4()),
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_thread_id=runtime_thread_id,
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

    approval = approvals.create_pending(
        "mcpServer/elicitation/request",
        {
            "threadId": runtime_thread_id,
            "serverName": "order",
            "message": "取消订单",
            "meta": {"codex_approval_kind": "mcp_tool_call"},
        },
        approval_key="a" * 64,
        conversation_id=conversation.id,
        requester_user_id="user-1",
        tenant_id="tenant-a",
    )

    assert approvals.find_actionable(conversation.id, "a" * 64).id == approval.id
    assert approvals.list_for_tenant("tenant-b") == []

    approved = approvals.decide(
        approval.id,
        "approve",
        decided_by="approver-a",
        tenant_id="tenant-a",
    )
    assert approved.status == "APPROVED"

    consumed = approvals.consume_approved_grant(approval.id)
    assert consumed is not None
    assert consumed.status == "CONSUMED"

    approvals.close()
    conversations.close()
