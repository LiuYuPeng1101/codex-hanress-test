from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_approval_service
from app.approval.approval_repository import ApprovalRequest
from app.approval.approval_service import ApprovalService
from app.schemas.approval import ApprovalListResponse, ApprovalResponse
from app.security.service_auth import ServicePrincipal, require_approval_principal

router = APIRouter(prefix="/approvals", tags=["Approval"])


def _to_response(item: ApprovalRequest) -> ApprovalResponse:
    message = item.params.get("message")
    return ApprovalResponse(
        id=item.id,
        conversation_id=item.conversation_id,
        requester_user_id=item.requester_user_id,
        tenant_id=item.tenant_id,
        server_name=item.server_name,
        message=message if isinstance(message, str) else "Agent 请求执行受控操作",
        status=item.status,
        created_at=item.created_at,
        decided_at=item.decided_at,
        decision=item.decision,
        decided_by=item.decided_by,
    )


@router.get("", response_model=ApprovalListResponse)
def list_approvals(
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    principal: Annotated[ServicePrincipal, Depends(require_approval_principal)],
) -> ApprovalListResponse:
    return ApprovalListResponse(
        items=[_to_response(item) for item in service.list_approvals(tenant_id=principal.tenant_id)]
    )


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: str,
    service: Annotated[ApprovalService, Depends(get_approval_service)],
    principal: Annotated[ServicePrincipal, Depends(require_approval_principal)],
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
    principal: Annotated[ServicePrincipal, Depends(require_approval_principal)],
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
