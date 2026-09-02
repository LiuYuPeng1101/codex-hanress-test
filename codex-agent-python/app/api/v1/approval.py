from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_approval_service
from app.approval.approval_service import ApprovalService
from app.approval.approval_store import ApprovalRequest
from app.schemas.approval import ApprovalListResponse, ApprovalResponse

router = APIRouter(prefix="/approvals", tags=["Approval"])


def _to_response(item: ApprovalRequest) -> ApprovalResponse:
    """把内部审批对象转换成对外 API Response。"""

    return ApprovalResponse(
        id=item.id,
        method=item.method,
        params=item.params,
        status=item.status,
        created_at=item.created_at,
        decided_at=item.decided_at,
        decision=item.decision,
    )


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> ApprovalListResponse:
    """查询审批记录。

    当 cancel_order 触发 MCP Tool Approval 时，会先出现一条 PENDING 记录。
    """

    return ApprovalListResponse(
        items=[_to_response(item) for item in service.list_approvals()]
    )


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve(
    approval_id: str,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> ApprovalResponse:
    """批准本次 Agent 操作，并让等待中的 Codex Turn 继续执行。"""

    try:
        return _to_response(service.approve(approval_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="审批记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject(
    approval_id: str,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
) -> ApprovalResponse:
    """拒绝本次 Agent 操作，Codex 会收到 decline，Tool 不应真正执行。"""

    try:
        return _to_response(service.reject(approval_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="审批记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
