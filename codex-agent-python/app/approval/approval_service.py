from __future__ import annotations

from typing import Any

from app.approval.approval_repository import ApprovalRepository, ApprovalTimeoutError
from app.conversations.conversation_repository import ConversationRepository


class ApprovalService:
    """连接 Codex approval handler 与企业多租户审批中心。"""

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(
        self,
        repository: ApprovalRepository,
        conversations: ConversationRepository,
        timeout_seconds: int,
    ) -> None:
        self._repository = repository
        self._conversations = conversations
        self._timeout_seconds = timeout_seconds

    def handle_codex_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        payload = params or {}
        if method != self.MCP_APPROVAL_METHOD:
            return {}

        meta = payload.get("meta") or payload.get("_meta") or {}
        if meta.get("codex_approval_kind") != "mcp_tool_call":
            return {}

        thread_id = payload.get("threadId") or payload.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return {"action": "decline", "content": None}

        try:
            conversation = self._conversations.find_by_runtime_thread_id(thread_id)
        except KeyError:
            # 来源不明的 Runtime Thread 不能进入企业审批中心，更不能执行写操作。
            return {"action": "decline", "content": None}

        approval = self._repository.create(
            method,
            payload,
            conversation_id=conversation.id,
            requester_user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
        )
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
