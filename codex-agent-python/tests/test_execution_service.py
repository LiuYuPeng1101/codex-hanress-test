from unittest.mock import Mock

import pytest

from app.executions.order_policy import validate_cancel_order
from app.executions.service import ExecutionService


def setup_service():
    store, conversations = Mock(), Mock()
    return (
        ExecutionService(store, conversations, {"order.cancel": validate_cancel_order}, 3600),
        store,
        conversations,
    )


def test_retry_has_stable_fingerprint_and_changed_intent_does_not():
    service, store, _ = setup_service()
    args = dict(
        conversation_id="c",
        user_id="u",
        tenant_id="t",
        operation="order.cancel",
        arguments={"orderId": "1001"},
    )
    service.prepare(**args)
    first = store.prepare_execution.call_args.kwargs["approval_key"]
    service.prepare(**args)
    assert store.prepare_execution.call_args.kwargs["approval_key"] == first
    for field, value in [
        ("conversation_id", "other"),
        ("user_id", "other"),
        ("tenant_id", "other"),
        ("arguments", {"orderId": "1002"}),
    ]:
        service.prepare(**(args | {field: value}))
        assert store.prepare_execution.call_args.kwargs["approval_key"] != first


def test_foreign_conversation_never_reaches_grant_store():
    service, store, conversations = setup_service()
    conversations.get_owned.side_effect = KeyError("foreign")
    with pytest.raises(KeyError):
        service.prepare(
            conversation_id="c",
            user_id="u",
            tenant_id="t",
            operation="order.cancel",
            arguments={"orderId": "1001"},
        )
    store.prepare_execution.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"orderId": 1001},
        {"orderId": ""},
        {"orderId": " 1001"},
        {"orderId": "a\nb"},
        {"orderId": "x" * 129},
        {"orderId": "1001", "execution_id": "forged"},
    ],
)
def test_invalid_or_forged_arguments_cannot_create_grants(arguments):
    service, store, _ = setup_service()
    with pytest.raises(ValueError):
        service.prepare(
            conversation_id="c",
            user_id="u",
            tenant_id="t",
            operation="order.cancel",
            arguments=arguments,
        )
    store.prepare_execution.assert_not_called()


def test_operation_registry_rejects_unknown_actions():
    service, store, _ = setup_service()
    with pytest.raises(ValueError, match="UNSUPPORTED_OPERATION"):
        service.prepare(
            conversation_id="c",
            user_id="u",
            tenant_id="t",
            operation="order.refund",
            arguments={"orderId": "1001"},
        )
    store.prepare_execution.assert_not_called()
