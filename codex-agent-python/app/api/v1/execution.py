import secrets
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_execution_service
from app.core.config import get_settings
from app.executions.service import ExecutionService
from app.security.service_auth import ServicePrincipal

router = APIRouter(prefix="/internal/executions", tags=["Internal execution authorization"])
_bearer = HTTPBearer(auto_error=False)


def require_execution_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    user_id: Annotated[str | None, Header(alias="X-User-Id", max_length=128)] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id", max_length=128)] = None,
) -> ServicePrincipal:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials,
        get_settings().execution_service_secret,
    ):
        raise HTTPException(status_code=401, detail="执行授权服务认证失败")
    if not user_id or not user_id.strip() or not tenant_id or not tenant_id.strip():
        raise HTTPException(status_code=400, detail="缺少可信业务身份")
    return ServicePrincipal(user_id.strip(), tenant_id.strip(), frozenset())


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    operation: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class ExecutionResponse(BaseModel):
    status: Literal["PENDING", "AUTHORIZED", "REJECTED", "EXPIRED"]
    approval_id: UUID
    execution_id: UUID | None
    expires_at: datetime


@router.post("/prepare", response_model=ExecutionResponse)
def prepare_execution(
    body: ExecutionRequest,
    service: Annotated[ExecutionService, Depends(get_execution_service)],
    principal: Annotated[ServicePrincipal, Depends(require_execution_principal)],
) -> ExecutionResponse:
    try:
        result = service.prepare(
            conversation_id=str(body.conversation_id),
            operation=body.operation,
            arguments=body.arguments,
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="不支持的操作或无效参数") from exc
    return ExecutionResponse(
        status=result.status,
        approval_id=result.approval_id,
        execution_id=result.execution_id,
        expires_at=result.expires_at,
    )
