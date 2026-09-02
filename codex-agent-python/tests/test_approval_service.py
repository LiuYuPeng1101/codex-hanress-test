from datetime import datetime, timezone
from unittest.mock import Mock

from app.approval.approval_repository import ApprovalRequest, ApprovalTimeoutError
from app.approval.approval_service import ApprovalService
from app.conversations.conversation_repository import Conversation


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-1",
        agent_id="order-agent",
        tenant_id="tenant-a",
        user_id="requester-1",
        runtime_type="codex",
        runtime_thread_id="thread-1",
        runtime_instance_id="runtime-01",
        created_at=datetime.now(timezone.utc),
    )


def _pending_approval() -> ApprovalRequest:
    return ApprovalRequest(
        id="approval-1",
        conversation_id="conversation-1",
        requester_user_id="requester-1",
        tenant_id="tenant-a",
        method="mcpServer/elicitation/request",
        thread_id="thread-1",
        turn_id="turn-1",
        server_name="order",
        params={
            "threadId": "thread-1",
            "turnId": "turn-1",
            "serverName": "order",
            "meta": {"codex_approval_kind": "mcp_tool_call"},
        },
        status="PENDING",
        created_at=datetime.now(timezone.utc),
        decided_at=None,
        decision=None,
        decided_by=None,
    )


def _service(*, decision: str | None = None) -> tuple[ApprovalService, Mock, Mock]:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.return_value = _conversation()
    repository.create.return_value = _pending_approval()
    if decision is not None:
        repository.wait_for_decision.return_value = decision
    service = ApprovalService(repository, conversations, timeout_seconds=900)
    return service, repository, conversations


def test_mcp_tool_approval_accepts_after_human_approval() -> None:
    service, repository, _ = _service(decision="approve")

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "accept", "content": {}}
    repository.create.assert_called_once_with(
        "mcpServer/elicitation/request",
        _pending_approval().params,
        conversation_id="conversation-1",
        requester_user_id="requester-1",
        tenant_id="tenant-a",
    )


def test_mcp_tool_approval_declines_after_human_rejection() -> None:
    service, _, _ = _service(decision="reject")

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "decline", "content": None}


def test_mcp_tool_approval_declines_on_timeout() -> None:
    service, repository, _ = _service()
    repository.wait_for_decision.side_effect = ApprovalTimeoutError("timeout")

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "decline", "content": None}


def test_unknown_runtime_thread_fails_closed() -> None:
    repository = Mock()
    conversations = Mock()
    conversations.find_by_runtime_thread_id.side_effect = KeyError("thread-unknown")
    service = ApprovalService(repository, conversations, timeout_seconds=900)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        {
            "threadId": "thread-unknown",
            "meta": {"codex_approval_kind": "mcp_tool_call"},
        },
    )

    assert result == {"action": "decline", "content": None}
    repository.create.assert_not_called()


def test_human_decision_carries_trusted_actor_and_tenant() -> None:
    service, repository, _ = _service()
    repository.decide.return_value = _pending_approval()

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
    repository.create.assert_not_called()
