import threading
import time

from app.approval.approval_store import ApprovalStore


def test_approval_store_can_approve_and_wake_waiter() -> None:
    """批准后应把 PENDING 改为 APPROVED，并唤醒等待线程。"""

    store = ApprovalStore()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    result: list[str] = []

    waiter = threading.Thread(target=lambda: result.append(store.wait_for_decision(item.id)))
    waiter.start()

    time.sleep(0.05)
    store.decide(item.id, "approve")
    waiter.join(timeout=1)

    assert result == ["approve"]
    assert item.status == "APPROVED"


def test_approval_store_can_reject() -> None:
    """拒绝后应记录 REJECTED。"""

    store = ApprovalStore()
    item = store.create("mcpServer/elicitation/request", {"meta": {}})
    store.decide(item.id, "reject")

    assert store.wait_for_decision(item.id) == "reject"
    assert item.status == "REJECTED"
