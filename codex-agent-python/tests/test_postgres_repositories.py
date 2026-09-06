import os
import uuid

import pytest

from app.approval.approval_repository import ApprovalRepository
from app.conversations.conversation_repository import ConversationRepository


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL 未配置")
    return value


def test_conversation_mapping_and_approval_isolation() -> None:
    database_url = _database_url()
    conversations = ConversationRepository(database_url)
    approvals = ApprovalRepository(database_url)

    runtime_thread_id = f"thread-{uuid.uuid4()}"
    conversation = conversations.create(
        conversation_id=str(uuid.uuid4()),
        tenant_id="tenant-a",
        user_id="user-1",
        runtime_thread_id=runtime_thread_id,
    )

    assert (
        conversations.get_owned(
            conversation.id,
            tenant_id="tenant-a",
            user_id="user-1",
        ).runtime_thread_id
        == runtime_thread_id
    )

    with pytest.raises(KeyError):
        conversations.get_owned(
            conversation.id,
            tenant_id="tenant-b",
            user_id="user-1",
        )

    approval = approvals.create_pending(
        "mcpServer/elicitation/request",
        {
            "threadId": runtime_thread_id,
            "serverName": "order",
            "message": "取消订单",
            "meta": {"codex_approval_kind": "mcp_tool_call"},
        },
        approval_key="a" * 64,
        conversation_id=conversation.id,
        requester_user_id="user-1",
        tenant_id="tenant-a",
    )

    assert approvals.find_actionable(conversation.id, "a" * 64).id == approval.id
    assert approvals.list_for_tenant("tenant-b") == []

    approved = approvals.decide(
        approval.id,
        "approve",
        decided_by="approver-a",
        tenant_id="tenant-a",
    )
    assert approved.status == "APPROVED"

    consumed = approvals.consume_approved_grant(approval.id)
    assert consumed is not None
    assert consumed.status == "CONSUMED"

    approvals.close()
    conversations.close()


def test_execution_grant_concurrency_restart_rejection_and_expiry():
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import func, text, update

    from app.approval.approval_repository import approval_requests
    from app.executions.order_policy import validate_cancel_order
    from app.executions.service import ExecutionService

    url = _database_url()
    conversations, approvals = ConversationRepository(url), ApprovalRepository(url)
    cid = str(uuid.uuid4())
    conversations.create(
        conversation_id=cid,
        tenant_id="execution-tenant",
        user_id="owner",
        runtime_thread_id=str(uuid.uuid4()),
    )
    service = ExecutionService(
        approvals, conversations, {"order.cancel": validate_cancel_order}, 3600
    )
    args = dict(
        conversation_id=cid,
        user_id="owner",
        tenant_id="execution-tenant",
        operation="order.cancel",
        arguments={"orderId": "1001"},
    )
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = list(pool.map(lambda _: service.prepare(**args), range(16)))
        assert {item.approval_id for item in pending} == {pending[0].approval_id}
        assert all(item.status == "PENDING" and item.execution_id is None for item in pending)
        aid = pending[0].approval_id
        with pytest.raises(KeyError):
            approvals.decide(aid, "approve", decided_by="reviewer", tenant_id="foreign")
        approvals.decide(aid, "approve", decided_by="reviewer", tenant_id="execution-tenant")
        assert approvals.consume_approved_grant(aid) is None  # legacy SDK cannot consume this grant
        with ThreadPoolExecutor(max_workers=8) as pool:
            issued = list(pool.map(lambda _: service.prepare(**args), range(16)))
        execution_id = issued[0].execution_id
        assert execution_id is not None
        assert all(
            item.status == "AUTHORIZED" and item.execution_id == execution_id for item in issued
        )
        approvals.close()
        approvals = ApprovalRepository(url)  # no process-local grant/id cache survives this
        service = ExecutionService(
            approvals, conversations, {"order.cancel": validate_cancel_order}, 3600
        )
        assert service.prepare(**args).execution_id == execution_id
        # A lost OMS response cannot create a new ID. TTL expiration also must not do so.
        with approvals._engine.begin() as conn:
            conn.execute(
                update(approval_requests)
                .where(approval_requests.c.id == aid)
                .values(expires_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
            )
        expired = service.prepare(**args)
        assert expired.status == "EXPIRED" and expired.execution_id is None
        assert expired.approval_id == aid
        assert approvals.get(aid).execution_id == execution_id
        with pytest.raises(ValueError):
            approvals.decide(aid, "approve", decided_by="reviewer", tenant_id="execution-tenant")
        args["arguments"] = {"orderId": "1002"}
        rejected = service.prepare(**args)
        approvals.decide(
            rejected.approval_id, "reject", decided_by="reviewer", tenant_id="execution-tenant"
        )
        again = service.prepare(**args)
        assert again.status == "REJECTED" and again.execution_id is None
        assert again.approval_id == rejected.approval_id
        args["arguments"] = {"orderId": "1003"}
        pending_expiry = service.prepare(**args)
        with approvals._engine.begin() as conn:
            conn.execute(
                update(approval_requests)
                .where(approval_requests.c.id == pending_expiry.approval_id)
                .values(expires_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
            )
        with pytest.raises(ValueError):
            approvals.decide(
                pending_expiry.approval_id,
                "approve",
                decided_by="reviewer",
                tenant_id="execution-tenant",
            )
        assert service.prepare(**args).status == "EXPIRED"
    finally:
        approvals.close()
        conversations.close()


def test_database_deadlines_and_approval_pagination():
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.approval.pagination import decode_cursor, encode_cursor
    from app.core.database import DatabasePolicy

    url = _database_url()
    approvals = ApprovalRepository(url, DatabasePolicy(statement_ms=200, lock_ms=100))
    conversations = ConversationRepository(url)
    tenant = f"page-{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    conversations.create(
        conversation_id=cid, tenant_id=tenant, user_id="owner", runtime_thread_id=str(uuid.uuid4())
    )
    try:
        with approvals._engine.connect() as conn:
            assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "200ms"
            assert conn.execute(text("SHOW lock_timeout")).scalar_one() == "100ms"
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT pg_sleep(1)"))
        ids = []
        for i in range(105):
            item = approvals.create_pending(
                "legacy",
                {},
                approval_key=f"{i:064x}",
                conversation_id=cid,
                requester_user_id="owner",
                tenant_id=tenant,
            )
            ids.append(item.id)
        found, before = [], None
        while True:
            page = approvals.list_for_tenant(
                tenant, 23, status="PENDING", conversation_id=cid, before=before
            )
            if not page:
                break
            found.extend(item.id for item in page)
            before = decode_cursor(encode_cursor(page[-1].created_at, page[-1].id))
        assert len(found) == len(set(found)) == 105
        assert set(found) == set(ids)
        with pytest.raises(KeyError):
            approvals.get_for_tenant(ids[0], "foreign")
        assert approvals.get_for_tenant(ids[0], tenant).id == ids[0]
        approvals.decide(ids[0], "reject", decided_by="reviewer", tenant_id=tenant)
        assert len(approvals.list_for_tenant(tenant, 200, status="REJECTED")) == 1
    finally:
        approvals.close()
        conversations.close()
