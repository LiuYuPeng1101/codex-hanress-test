import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.approval.approval_repository import ApprovalRepository
from app.conversations.conversation_repository import ConversationRepository


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL 未配置")
    return value


def test_conversation_lease_and_approval_tenant_isolation() -> None:
    database_url = _database_url()
    conversations = ConversationRepository(database_url)
    approvals = ApprovalRepository(database_url)

    runtime_thread_id = f"thread-{uuid.uuid4()}"
    conversation_id = str(uuid.uuid4())
    conversation = conversations.create(
        conversation_id=conversation_id,
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_type="codex",
        runtime_thread_id=runtime_thread_id,
        runtime_instance_id="runtime-01",
        lease_seconds=30,
    )

    assert conversation.runtime_lease_owner == "runtime-01"
    assert conversations.acquire_lease(
        conversation.id,
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_instance_id="runtime-02",
        lease_seconds=30,
    ) is None

    # 模拟 Worker 失联后 lease 过期，另一个 Worker 应能接管同一 runtime_thread_id。
    with conversations._engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE conversations "
                "SET runtime_lease_expires_at = :expired "
                "WHERE id = :conversation_id"
            ),
            {
                "expired": datetime.now(timezone.utc) - timedelta(seconds=1),
                "conversation_id": conversation.id,
            },
        )

    taken_over = conversations.acquire_lease(
        conversation.id,
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_instance_id="runtime-02",
        lease_seconds=30,
    )
    assert taken_over is not None
    assert taken_over.runtime_lease_owner == "runtime-02"
    assert taken_over.runtime_thread_id == runtime_thread_id

    with pytest.raises(KeyError):
        conversations.get_owned(
            conversation.id,
            tenant_id="tenant-b",
            user_id="user-1",
        )

    approval_key = uuid.uuid4().hex
    approval = approvals.create_pending(
        "mcpServer/elicitation/request",
        {
            "threadId": runtime_thread_id,
            "turnId": "turn-1",
            "serverName": "order",
            "_meta": {
                "codex_approval_kind": "mcp_tool_call",
                "tool_params": {"orderId": "88201"},
            },
        },
        approval_key=approval_key,
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

    consumed = approvals.consume_approved_grant(approval.id)
    assert consumed is not None
    assert consumed.status == "CONSUMED"
    assert consumed.consumed_at is not None
    assert approvals.consume_approved_grant(approval.id) is None

    approvals.close()
    conversations.close()
