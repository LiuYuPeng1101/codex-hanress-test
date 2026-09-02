import threading
import time

import fakeredis

from app.approval.approval_store import ApprovalStore


def _store() -> ApprovalStore:
    redis = fakeredis.FakeRedis(decode_responses=False)
    return ApprovalStore(redis, wait_timeout_seconds=2)


def test_approval_store_can_approve_and_wake_waiter() -> None:
    store = _store()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    result: list[str] = []

    waiter = threading.Thread(target=lambda: result.append(store.wait_for_decision(item.id)))
    waiter.start()

    time.sleep(0.05)
    updated = store.decide(item.id, "approve")
    waiter.join(timeout=1)

    assert result == ["approve"]
    assert updated.status == "APPROVED"


def test_approval_store_can_reject() -> None:
    store = _store()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    updated = store.decide(item.id, "reject")

    assert store.wait_for_decision(item.id) == "reject"
    assert updated.status == "REJECTED"
