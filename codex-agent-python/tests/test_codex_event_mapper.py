from openai_codex.generated.v2_all import (
    AgentMessageDeltaNotification,
    ItemStartedNotification,
    TurnCompletedNotification,
)
from openai_codex.models import Notification

from app.events.codex_event_mapper import CodexEventMapper


def test_maps_sdk_message_delta_without_runtime_ids():
    event = CodexEventMapper().map(
        Notification(
            method="item/agentMessage/delta",
            payload=AgentMessageDeltaNotification(
                delta="订单已发货",
                itemId="item-1",
                threadId="thread-1",
                turnId="turn-1",
            ),
        ),
        "conversation-1",
    )
    assert event.type == "message.delta"
    assert event.data == {"delta": "订单已发货"}
    assert "thread-1" not in str(event.to_dict())


def test_maps_sdk_mcp_tool_without_arguments_or_results():
    notification = Notification(
        method="item/started",
        payload=ItemStartedNotification.model_validate(
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "startedAtMs": 0,
                "item": {
                    "id": "item-1",
                    "type": "mcpToolCall",
                    "server": "order",
                    "tool": "get_order_status",
                    "arguments": {"orderId": "secret"},
                    "status": "inProgress",
                },
            }
        ),
    )
    event = CodexEventMapper().map(notification, "conversation-1")
    assert event.type == "tool.started"
    assert event.data["tool_name"] == "get_order_status"
    assert "secret" not in str(event.to_dict())


def test_completed_error_is_sanitized_using_sdk_contract():
    notification = Notification(
        method="turn/completed",
        payload=TurnCompletedNotification(
            threadId="thread-1",
            turn={
                "id": "turn-1",
                "items": [],
                "itemsView": "full",
                "status": "failed",
                "error": {
                    "message": "Bearer sensitive-token",
                    "codexErrorInfo": None,
                    "additionalDetails": "private endpoint",
                },
            },
        ),
    )
    event = CodexEventMapper().map(notification, "conversation-1")
    assert event.data == {"status": "failed", "error": {"code": "TURN_FAILED"}}


def test_filters_reasoning_event():
    # Unsupported methods must not inspect or serialize arbitrary payloads.
    assert (
        CodexEventMapper().map(
            Notification(method="item/reasoning/textDelta", payload=None),
            "conversation-1",
        )
        is None
    )
