from __future__ import annotations

from typing import Any

from app.events.models import AgentEvent


class CodexEventMapper:
    """把 Codex 原始 Notification 映射成稳定、安全的 AgentEvent。"""

    _SUPPORTED_METHODS = {
        "turn/started",
        "turn/completed",
        "item/started",
        "item/completed",
        "item/agentMessage/delta",
    }

    def map(self, notification: Any, conversation_id: str) -> AgentEvent | None:
        """只输出业务层需要的安全事件，不暴露 Runtime Thread / Turn ID。"""

        method = getattr(notification, "method", None)
        if method not in self._SUPPORTED_METHODS:
            return None

        params = self._to_dict(getattr(notification, "params", None))

        if method == "turn/started":
            return AgentEvent("turn.started", conversation_id)

        if method == "turn/completed":
            turn = self._to_dict(params.get("turn"))
            return AgentEvent(
                "turn.completed",
                conversation_id,
                self._pick(turn, "status", "error", "durationMs"),
            )

        if method == "item/agentMessage/delta":
            return AgentEvent(
                "message.delta",
                conversation_id,
                {"delta": params.get("delta", "")},
            )

        item = self._to_dict(params.get("item"))
        item_type = item.get("type", "unknown")
        event_type = "item.started" if method == "item/started" else "item.completed"
        data: dict[str, Any] = {
            "item_id": item.get("id"),
            "item_type": item_type,
        }

        if item_type in {"mcpToolCall", "mcp_tool_call"}:
            data.update(
                {
                    "server": item.get("server"),
                    "tool_name": item.get("toolName") or item.get("tool_name"),
                    "status": item.get("status"),
                }
            )
            event_type = "tool.started" if method == "item/started" else "tool.completed"

        return AgentEvent(event_type, conversation_id, data)

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=True, mode="json")
        return {}

    @staticmethod
    def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
        return {key: source[key] for key in keys if key in source and source[key] is not None}
