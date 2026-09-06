from __future__ import annotations

from typing import Any

from app.approval.approval_repository import ApprovalRepository
from app.conversations.conversation_repository import ConversationRepository


class ApprovalService:
    """人工审批管理；业务执行授权由 ExecutionService 和持久化仓储完成。"""

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(
        self,
        repository: ApprovalRepository,
        conversations: ConversationRepository,
    ) -> None:
        self._repository = repository
        self._conversations = conversations

    def handle_codex_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        # SDK prose/metadata is not an authoritative business operation descriptor.
        # Business grants are created by the authenticated execution endpoint only.
        if method == self.MCP_APPROVAL_METHOD:
            return {"action": "decline", "content": None}
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            return {"decision": "decline"}
        return {}

    def list_approvals(self, *, tenant_id: str):
        return self._repository.list_for_tenant(tenant_id)

    def approve(self, approval_id: str, *, user_id: str, tenant_id: str):
        return self._repository.decide(
            approval_id,
            "approve",
            decided_by=user_id,
            tenant_id=tenant_id,
        )

    def reject(self, approval_id: str, *, user_id: str, tenant_id: str):
        return self._repository.decide(
            approval_id,
            "reject",
            decided_by=user_id,
            tenant_id=tenant_id,
        )
