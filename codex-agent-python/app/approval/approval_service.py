from __future__ import annotations

from typing import Any

from app.approval.approval_repository import ApprovalRepository, ApprovalTimeoutError


class ApprovalService:
    """连接 Codex approval handler 与企业审批中心的应用服务。"""

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(self, repository: ApprovalRepository, timeout_seconds: int) -> None:
        self._repository = repository
        self._timeout_seconds = timeout_seconds

    def handle_codex_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """处理 Codex App Server 主动发来的 MCP Tool Approval 请求。

        只有 `codex_approval_kind=mcp_tool_call` 才进入企业审批流程。审批记录先持久化，
        然后同步等待外部审批中心写入 approve/reject；等待超时按拒绝处理，避免危险操作失控。
        """

        payload = params or {}
        if method != self.MCP_APPROVAL_METHOD:
            return {}

        meta = payload.get("meta") or payload.get("_meta") or {}
        if meta.get("codex_approval_kind") != "mcp_tool_call":
            return {}

        approval = self._repository.create(method, payload)
        try:
            decision = self._repository.wait_for_decision(
                approval.id,
                timeout_seconds=self._timeout_seconds,
            )
        except ApprovalTimeoutError:
            return {"action": "decline", "content": None}

        if decision == "approve":
            return {"action": "accept", "content": {}}
        return {"action": "decline", "content": None}

    def list_approvals(self):
        return self._repository.list_all()

    def approve(self, approval_id: str, *, user_id: str, tenant_id: str):
        return self._repository.decide(
            approval_id,
            "approve",
            decided_by=user_id,
            decided_tenant_id=tenant_id,
        )

    def reject(self, approval_id: str, *, user_id: str, tenant_id: str):
        return self._repository.decide(
            approval_id,
            "reject",
            decided_by=user_id,
            decided_tenant_id=tenant_id,
        )
