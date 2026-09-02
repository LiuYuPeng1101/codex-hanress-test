from types import SimpleNamespace

from app.events.codex_event_mapper import CodexEventMapper


def test_maps_agent_message_delta_without_runtime_ids():
    mapper = CodexEventMapper()
    notification = SimpleNamespace(
        method="item/agentMessage/delta",
        params={"delta": "订单已发货"},
    )

    event = mapper.map(notification, "conversation-1")

    assert event is not None
    assert event.type == "message.delta"
    assert event.conversation_id == "conversation-1"
    assert event.data == {"delta": "订单已发货"}
    assert "thread_id" not in event.to_dict()
    assert "turn_id" not in event.to_dict()


def test_maps_mcp_tool_without_exposing_arguments():
    mapper = CodexEventMapper()
    notification = SimpleNamespace(
        method="item/started",
        params={
            "item": {
                "id": "item-1",
                "type": "mcpToolCall",
                "server": "order",
                "toolName": "get_order_status",
                "arguments": {"orderId": "sensitive-order-id"},
                "status": "inProgress",
            }
        },
    )

    event = mapper.map(notification, "conversation-1")

    assert event is not None
    assert event.type == "tool.started"
    assert event.data["tool_name"] == "get_order_status"
    assert "arguments" not in event.data


def test_filters_reasoning_event():
    mapper = CodexEventMapper()
    notification = SimpleNamespace(
        method="item/reasoning/textDelta",
        params={"delta": "内部推理内容"},
    )

    assert mapper.map(notification, "conversation-1") is None
