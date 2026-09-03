from __future__ import annotations

import hashlib
import json
from typing import Any

from app.approval.approval_repository import ApprovalRepository
from app.conversations.conversation_repository import ConversationRepository


class ApprovalService:
    """连接 Codex pre-execution approval 与企业人工审批中心。

    这里不再同步等待人工操作。第一次风险动作创建 PENDING 并立即 decline；人工批准后，
    下一次相同动作会原子消费一次 APPROVED grant 并返回 accept。这样审批可以跨进程重启、
    跨分钟/小时等待，不依赖某个长连接或 Python Event。
    """

    MCP_APPROVAL_METHOD = "mcpServer/elicitation/request"

    def __init__(
        self,
        repository: ApprovalRepository,
        conversations: ConversationRepository,
    ) -> None:
        self._repository = repository
        self._conversations = conversations

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

        approval_key = self._approval_key(conversation.id, payload)
        existing = self._repository.find_actionable(conversation.id, approval_key)
        if existing is not None:
            if existing.status == "APPROVED":
                consumed = self._repository.consume_approved_grant(existing.id)
                if consumed is not None:
                    return {"action": "accept", "content": {}}
            # PENDING 或并发请求已经先消费同一 grant 时都 fail closed。
            return {"action": "decline", "content": None}

        self._repository.create_pending(
            method,
            payload,
            approval_key=approval_key,
            conversation_id=conversation.id,
            requester_user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
        )
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

    @staticmethod
    def _approval_key(conversation_id: str, payload: dict[str, Any]) -> str:
        """为一次业务动作生成跨 Turn 稳定的审批指纹。

        threadId/turnId 不参与哈希，因为用户批准后重试通常会产生新的 Turn。
        优先使用 Codex MCP approval meta 中的结构化 tool_params；没有时才退回 message。
        """

        meta = payload.get("meta") or payload.get("_meta") or {}
        normalized = {
            "conversation_id": conversation_id,
            "server_name": payload.get("serverName") or payload.get("server_name"),
            "tool_description": meta.get("tool_description"),
            "tool_params": meta.get("tool_params"),
            "message": payload.get("message") if meta.get("tool_params") is None else None,
        }
        canonical = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
