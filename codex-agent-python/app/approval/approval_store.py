from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from redis import Redis
from redis.exceptions import WatchError


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """持久化审批记录。"""

    id: str
    method: str
    params: dict[str, Any]
    status: str
    created_at: datetime
    decided_at: datetime | None
    decision: str | None


class ApprovalStore:
    """基于 Redis 的 Approval Repository。

    审批状态和等待信号都存放在 Redis 中，因此 Agent Service 重启或扩容后不会依赖
    单个 Python 进程内存。等待中的 SDK handler 使用 Redis BLPOP 等待审批结果。
    """

    _INDEX_KEY = "agent:approvals:created"

    def __init__(self, redis: Redis, *, wait_timeout_seconds: int) -> None:
        self._redis = redis
        self._wait_timeout_seconds = wait_timeout_seconds

    def create(self, method: str, params: dict[str, Any]) -> ApprovalRequest:
        approval_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        key = self._record_key(approval_id)

        self._redis.hset(
            key,
            mapping={
                "id": approval_id,
                "method": method,
                "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                "status": "PENDING",
                "created_at": created_at.isoformat(),
                "decided_at": "",
                "decision": "",
            },
        )
        self._redis.zadd(self._INDEX_KEY, {approval_id: created_at.timestamp()})
        return self.get(approval_id)

    def list_all(self, *, limit: int = 100) -> list[ApprovalRequest]:
        ids = self._redis.zrevrange(self._INDEX_KEY, 0, max(limit - 1, 0))
        items: list[ApprovalRequest] = []
        for raw_id in ids:
            approval_id = self._decode(raw_id)
            try:
                items.append(self.get(approval_id))
            except KeyError:
                self._redis.zrem(self._INDEX_KEY, approval_id)
        return items

    def get(self, approval_id: str) -> ApprovalRequest:
        payload = self._redis.hgetall(self._record_key(approval_id))
        if not payload:
            raise KeyError(approval_id)
        decoded = {self._decode(k): self._decode(v) for k, v in payload.items()}
        return ApprovalRequest(
            id=decoded["id"],
            method=decoded["method"],
            params=json.loads(decoded["params"]),
            status=decoded["status"],
            created_at=datetime.fromisoformat(decoded["created_at"]),
            decided_at=(
                datetime.fromisoformat(decoded["decided_at"])
                if decoded.get("decided_at")
                else None
            ),
            decision=decoded.get("decision") or None,
        )

    def decide(self, approval_id: str, decision: str) -> ApprovalRequest:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision 只能是 approve 或 reject")

        status = "APPROVED" if decision == "approve" else "REJECTED"
        return self._transition(
            approval_id,
            status=status,
            decision=decision,
            notify_waiter=True,
        )

    def expire(self, approval_id: str) -> ApprovalRequest:
        """将仍处于 PENDING 的审批原子标记为 EXPIRED。"""

        return self._transition(
            approval_id,
            status="EXPIRED",
            decision=None,
            notify_waiter=False,
        )

    def wait_for_decision(self, approval_id: str) -> str:
        """等待跨进程可见的人工审批结果。"""

        current = self.get(approval_id)
        if current.decision:
            return current.decision
        if current.status != "PENDING":
            raise TimeoutError(f"审批已失效: {approval_id}")

        result = self._redis.blpop(
            self._decision_key(approval_id),
            timeout=self._wait_timeout_seconds,
        )
        if result is None:
            raise TimeoutError(f"审批等待超时: {approval_id}")
        return self._decode(result[1])

    def _transition(
        self,
        approval_id: str,
        *,
        status: str,
        decision: str | None,
        notify_waiter: bool,
    ) -> ApprovalRequest:
        record_key = self._record_key(approval_id)
        decision_key = self._decision_key(approval_id)
        decided_at = datetime.now(timezone.utc).isoformat()

        for _ in range(5):
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(record_key)
                    current_status = pipe.hget(record_key, "status")
                    if current_status is None:
                        raise KeyError(approval_id)
                    if self._decode(current_status) != "PENDING":
                        raise ValueError("该审批已经处理，不能重复变更")

                    pipe.multi()
                    pipe.hset(
                        record_key,
                        mapping={
                            "status": status,
                            "decision": decision or "",
                            "decided_at": decided_at,
                        },
                    )
                    if notify_waiter and decision is not None:
                        pipe.rpush(decision_key, decision)
                        pipe.expire(decision_key, self._wait_timeout_seconds)
                    pipe.execute()
                    return self.get(approval_id)
                except WatchError:
                    continue
        raise RuntimeError("审批记录发生并发更新，请重试")

    @staticmethod
    def _record_key(approval_id: str) -> str:
        return f"agent:approval:{approval_id}"

    @staticmethod
    def _decision_key(approval_id: str) -> str:
        return f"agent:approval:{approval_id}:decision"

    @staticmethod
    def _decode(value: bytes | str) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value
