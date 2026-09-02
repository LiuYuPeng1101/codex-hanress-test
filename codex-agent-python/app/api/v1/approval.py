from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_approval_service
from app.approval.approval_repository import ApprovalRequest
from app.approval.approval_service import ApprovalService
from app.schemas.approval import ApprovalListResponse, ApprovalResponse
from app.security.gateway_auth import GatewayPrincipal, require_gateway_principal

router = APIRouter(prefix="/approvals", tags=["Approval"])


def _to_response(item: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=item.id,
        method=item.method,
        thread_id=item.thread_id,
        turn_id=item.turn_id,
        server_name=item.server_name,
        params=item.params,
        status=item.status,
        created_at=item.created_at,
        decided_at=item.decided_at,
        decision=item.decision,
        decided_by=item.decided_by,
        decided_tenant_id=item.decided_tenant_id,
    )


@router.get("", response_model=ApprovalListResponse)
def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    _principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
) -> ApprovalListResponse:
    """查询最近审批记录。"""

    return ApprovalListResponse(items=[_to_response(item) for item in service.list_approvals()])


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: str,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
) -> ApprovalResponse:
    try:
        return _to_response(
            service.approve(
                approval_id,
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="审批记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
def reject(
    approval_id: str,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
) -> ApprovalResponse:
    try:
        return _to_response(
            service.reject(
                approval_id,
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="审批记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
