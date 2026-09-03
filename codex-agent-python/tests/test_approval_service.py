from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.approval.approval_repository import ApprovalRequest
from app.approval.approval_service import ApprovalService
from app.conversations.conversation_repository import Conversation


def _conversation() -> Conversation:
    now = datetime.now(timezone.utc)
    return Conversation(
        id="conversation-1",
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="requester-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_lease_owner="runtime-01",
        runtime_lease_expires_at=now + timedelta(seconds=30),
        runtime_generation=1,
        created_at=now,
    )


def _payload() -> dict:
    return {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "serverName": "order",
        "message": "Allow cancel_order?",
        "_meta": {
            "codex_approval_kind": "mcp_tool_call",
            "tool_description": "cancel_order",
            "tool_params": {"orderId": "88201"},
        },
    }


def _approval(status: str = "PENDING") -> ApprovalRequest:
    return ApprovalRequest(
        id="approval-1",
        approval_key="approval-key",
        conversation_id="conversation-1",
        requester_user_id="requester-1",
        tenant_id="tenant-a",
        method="mcpServer/elicitation/request",
        thread_id="thread-1",
        turn_id="turn-1",
        server_name="order",
        params=_payload(),
        status=status,
        created_at=datetime.now(timezone.utc),
        decided_at=None,
        decision=None,
        decided_by=None,
        consumed_at=None,
    )


def _service() -> tuple[ApprovalService, Mock, Mock]:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.return_value = _conversation()
    service = ApprovalService(repository, conversations)
    return service, repository, conversations


def test_first_risky_action_creates_pending_and_declines_immediately() -> None:
    service, repository, _ = _service()
    repository.find_actionable.return_value = None
    repository.create_pending.return_value = _approval()

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _payload(),
    )

    assert result == {"action": "decline", "content": None}
    repository.create_pending.assert_called_once()
    _, kwargs = repository.create_pending.call_args
    assert kwargs["conversation_id"] == "conversation-1"
    assert kwargs["requester_user_id"] == "requester-1"
    assert kwargs["tenant_id"] == "tenant-a"
    assert len(kwargs["approval_key"]) == 64


def test_pending_action_does_not_create_duplicate_request() -> None:
    service, repository, _ = _service()
    repository.find_actionable.return_value = _approval("PENDING")

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _payload(),
    )

    assert result == {"action": "decline", "content": None}
    repository.create_pending.assert_not_called()


def test_approved_grant_is_consumed_once_before_tool_execution() -> None:
    service, repository, _ = _service()
    approved = _approval("APPROVED")
    consumed = ApprovalRequest(
        **{
            field: getattr(approved, field)
            for field in approved.__dataclass_fields__
            if field not in {"status", "consumed_at"}
        },
        status="CONSUMED",
        consumed_at=datetime.now(timezone.utc),
    )
    repository.find_actionable.return_value = approved
    repository.consume_approved_grant.return_value = consumed

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _payload(),
    )

    assert result == {"action": "accept", "content": {}}
    repository.consume_approved_grant.assert_called_once_with("approval-1")


def test_concurrent_second_consumer_fails_closed() -> None:
    service, repository, _ = _service()
    repository.find_actionable.return_value = _approval("APPROVED")
    repository.consume_approved_grant.return_value = None

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _payload(),
    )

    assert result == {"action": "decline", "content": None}


def test_approval_key_is_stable_across_turn_ids() -> None:
    first = _payload()
    second = _payload()
    second["turnId"] = "turn-2"

    assert ApprovalService._approval_key("conversation-1", first) == ApprovalService._approval_key(
        "conversation-1", second
    )


def test_unknown_runtime_thread_fails_closed() -> None:
    service, repository, conversations = _service()
    conversations.find_by_runtime_thread_id.side_effect = KeyError("thread-unknown")

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        {
            "threadId": "thread-unknown",
            "_meta": {"codex_approval_kind": "mcp_tool_call"},
        },
    )

    assert result == {"action": "decline", "content": None}
    repository.create_pending.assert_not_called()


def test_human_decision_carries_trusted_actor_and_tenant() -> None:
    service, repository, _ = _service()
    repository.decide.return_value = _approval()

    service.approve("approval-1", user_id="approver-7", tenant_id="tenant-a")

    repository.decide.assert_called_once_with(
        "approval-1",
        "approve",
        decided_by="approver-7",
        tenant_id="tenant-a",
    )


def test_non_mcp_approval_request_is_not_interpreted_as_business_approval() -> None:
    service, repository, _ = _service()

    result = service.handle_codex_request("unknown/request", {})

    assert result == {}
    repository.create_pending.assert_not_called()
