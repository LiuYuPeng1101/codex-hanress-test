from datetime import datetime, timezone
from unittest.mock import Mock

from app.approval.approval_repository import ApprovalRequest
from app.approval.approval_service import ApprovalService
from app.conversations.conversation_repository import Conversation


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-1",
        tenant_id="tenant-a",
        user_id="requester-1",
        runtime_thread_id="thread-1",
        created_at=datetime.now(timezone.utc),
    )


def _approval(status: str = "PENDING") -> ApprovalRequest:
    return ApprovalRequest(
        id="approval-1",
        approval_key="key-1",
        conversation_id="conversation-1",
        requester_user_id="requester-1",
        tenant_id="tenant-a",
        method="mcpServer/elicitation/request",
        thread_id="thread-1",
        turn_id="turn-1",
        server_name="order",
        params={
            "threadId": "thread-1",
            "serverName": "order",
            "message": "取消订单1001",
            "meta": {
                "codex_approval_kind": "mcp_tool_call",
                "tool_description": "cancel_order",
                "tool_params": {"orderId": "1001"},
            },
        },
        status=status,
        created_at=datetime.now(timezone.utc),
        decided_at=None,
        decision=None,
        decided_by=None,
        consumed_at=None,
    )


def test_first_risky_action_creates_pending_and_declines() -> None:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.return_value = _conversation()
    repository.find_actionable.return_value = None
    repository.create_pending.return_value = _approval()
    service = ApprovalService(repository, conversations)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _approval().params,
    )

    assert result == {"action": "decline", "content": None}
    repository.create_pending.assert_called_once()


def test_approved_grant_is_consumed_before_tool_execution() -> None:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.return_value = _conversation()
    approved = _approval(status="APPROVED")
    repository.find_actionable.return_value = approved
    repository.consume_approved_grant.return_value = _approval(status="CONSUMED")
    service = ApprovalService(repository, conversations)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _approval().params,
    )

    assert result == {"action": "accept", "content": {}}
    repository.consume_approved_grant.assert_called_once_with("approval-1")


def test_unknown_thread_fails_closed() -> None:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.side_effect = KeyError("unknown")
    service = ApprovalService(repository, conversations)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        {"threadId": "unknown", "meta": {"codex_approval_kind": "mcp_tool_call"}},
    )

    assert result == {"action": "decline", "content": None}
    repository.create_pending.assert_not_called()
