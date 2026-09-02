from datetime import datetime, timezone
from unittest.mock import Mock

from app.approval.approval_repository import ApprovalRequest, ApprovalTimeoutError
from app.approval.approval_service import ApprovalService


def _pending_approval() -> ApprovalRequest:
    return ApprovalRequest(
        id="approval-1",
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
        decided_tenant_id=None,
    )


def test_mcp_tool_approval_accepts_after_human_approval() -> None:
    repository = Mock()
    repository.create.return_value = _pending_approval()
    repository.wait_for_decision.return_value = "approve"
    service = ApprovalService(repository, timeout_seconds=900)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "accept", "content": {}}


def test_mcp_tool_approval_declines_after_human_rejection() -> None:
    repository = Mock()
    repository.create.return_value = _pending_approval()
    repository.wait_for_decision.return_value = "reject"
    service = ApprovalService(repository, timeout_seconds=900)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "decline", "content": None}


def test_mcp_tool_approval_declines_on_timeout() -> None:
    repository = Mock()
    repository.create.return_value = _pending_approval()
    repository.wait_for_decision.side_effect = ApprovalTimeoutError("timeout")
    service = ApprovalService(repository, timeout_seconds=900)

    result = service.handle_codex_request(
        "mcpServer/elicitation/request",
        _pending_approval().params,
    )

    assert result == {"action": "decline", "content": None}


def test_human_decision_carries_trusted_actor_identity() -> None:
    repository = Mock()
    repository.decide.return_value = _pending_approval()
    service = ApprovalService(repository, timeout_seconds=900)

    service.approve("approval-1", user_id="user-7", tenant_id="tenant-a")

    repository.decide.assert_called_once_with(
        "approval-1",
        "approve",
        decided_by="user-7",
        decided_tenant_id="tenant-a",
    )


def test_non_mcp_approval_request_is_not_interpreted_as_business_approval() -> None:
    repository = Mock()
    service = ApprovalService(repository, timeout_seconds=900)

    result = service.handle_codex_request("unknown/request", {})

    assert result == {}
    repository.create.assert_not_called()
