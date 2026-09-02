from __future__ import annotations

from typing import Any

from app.events.models import AgentEvent


class CodexEventMapper:
    """把 Codex 原始 Notification 映射成稳定、安全的 AgentEvent。

    这里只允许少量适合前端展示的事件通过。reasoning 类事件、完整 Tool 参数、
    文件内容等默认不向前端透传；需要完整诊断信息时应进入受控的 Observability 后端。
    """

    _SUPPORTED_METHODS = {
        "turn/started",
        "turn/completed",
        "item/started",
        "item/completed",
        "item/agentMessage/delta",
    }

    def map(self, notification: Any, thread_id: str, turn_id: str) -> AgentEvent | None:
        """将一个 Codex Notification 转成 AgentEvent；不需要展示的事件返回 None。"""

        method = getattr(notification, "method", None)
        if method not in self._SUPPORTED_METHODS:
            return None

        params = self._to_dict(getattr(notification, "params", None))

        if method == "turn/started":
            return AgentEvent("turn.started", thread_id, turn_id)

        if method == "turn/completed":
            # 官方协议把 status / error 等字段放在 params.turn 内，而不是 params 顶层。
            turn = self._to_dict(params.get("turn"))
            return AgentEvent(
                "turn.completed",
                thread_id,
                turn_id,
                self._pick(turn, "status", "error", "durationMs"),
            )

        if method == "item/agentMessage/delta":
            # delta 是新增文本片段。这里只把最终展示文本推给浏览器。
            return AgentEvent(
                "message.delta",
                thread_id,
                turn_id,
                {"delta": params.get("delta", "")},
            )

        item = self._to_dict(params.get("item"))
        item_type = item.get("type", "unknown")
        event_type = "item.started" if method == "item/started" else "item.completed"

        data: dict[str, Any] = {
            "item_id": item.get("id"),
            "item_type": item_type,
        }

        # MCP Tool 事件只暴露 Tool 名称、Server 和状态，不把完整 arguments/result 推给前端。
        if item_type in {"mcpToolCall", "mcp_tool_call"}:
            data.update(
                {
                    "server": item.get("server"),
                    "tool_name": item.get("toolName") or item.get("tool_name"),
                    "status": item.get("status"),
                }
            )
            event_type = "tool.started" if method == "item/started" else "tool.completed"

        return AgentEvent(event_type, thread_id, turn_id, data)

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        """兼容 Pydantic Model 与普通 dict。"""

        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=True, mode="json")
        return {}

    @staticmethod
    def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
        """只挑选允许对外暴露的字段。"""

        return {key: source[key] for key in keys if key in source and source[key] is not None}
