from __future__ import annotations

from typing import Any

from app.approval.approval_store import ApprovalStore


class ApprovalService:
    """连接 Codex approval handler 与企业审批状态存储。"""

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def handle_codex_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """处理 Codex App Server 主动发来的 MCP Tool Approval。

        未识别的 Server Request 不应被误判为业务审批；MCP Tool Approval 超时时使用
        fail-closed 策略，记录 EXPIRED 并向 Codex 返回 decline。
        """

        payload = params or {}
        if method != self.MCP_APPROVAL_METHOD:
            return {}

        meta = payload.get("meta") or payload.get("_meta") or {}
        if meta.get("codex_approval_kind") != "mcp_tool_call":
            return {}

        approval = self._store.create(method, payload)
        try:
            decision = self._store.wait_for_decision(approval.id)
        except TimeoutError:
            try:
                self._store.expire(approval.id)
            except ValueError:
                # 超时边界上如果人工决策已提交，以最终持久化状态为准。
                current = self._store.get(approval.id)
                if current.decision == "approve":
                    return {"action": "accept", "content": {}}
            return {"action": "decline", "content": None}

        if decision == "approve":
            return {"action": "accept", "content": {}}
        return {"action": "decline", "content": None}

    def list_approvals(self):
        return self._store.list_all()

    def approve(self, approval_id: str):
        return self._store.decide(approval_id, "approve")

    def reject(self, approval_id: str):
        return self._store.decide(approval_id, "reject")
