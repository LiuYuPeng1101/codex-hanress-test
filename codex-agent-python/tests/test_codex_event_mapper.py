from types import SimpleNamespace

from app.events.codex_event_mapper import CodexEventMapper


def test_maps_agent_message_delta():
    mapper = CodexEventMapper()
    notification = SimpleNamespace(
        method="item/agentMessage/delta",
        params={"delta": "订单已发货"},
    )

    event = mapper.map(notification, "thread-1", "turn-1")

    assert event is not None
    assert event.type == "message.delta"
    assert event.data == {"delta": "订单已发货"}


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
                "arguments": {"orderId": "1001"},
                "status": "inProgress",
            }
        },
    )

    event = mapper.map(notification, "thread-1", "turn-1")

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

    assert mapper.map(notification, "thread-1", "turn-1") is None
