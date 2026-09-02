from __future__ import annotations

from typing import Any

from app.approval.approval_store import ApprovalStore


class ApprovalService:
    """连接 Codex approval handler 与业务审批 API 的应用服务。"""

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def handle_codex_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """处理 Codex App Server 主动发来的审批请求。

        只把 `codex_approval_kind=mcp_tool_call` 的 MCP Tool Approval 交给人工处理。
        其他未知 Server Request 默认返回空对象，避免误把它们当业务审批。
        """

        payload = params or {}
        if method != self.MCP_APPROVAL_METHOD:
            return {}

        meta = payload.get("meta") or payload.get("_meta") or {}
        if meta.get("codex_approval_kind") != "mcp_tool_call":
            return {}

        approval = self._store.create(method, payload)
        decision = self._store.wait_for_decision(approval.id)

        if decision == "approve":
            return {"action": "accept", "content": {}}
        return {"action": "decline", "content": None}

    def list_approvals(self):
        return self._store.list_all()

    def approve(self, approval_id: str):
        return self._store.decide(approval_id, "approve")

    def reject(self, approval_id: str):
        return self._store.decide(approval_id, "reject")
