from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    """调用当前单 Agent Service 的可信业务身份。"""

    user_id: str
    tenant_id: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        return role in self.roles


def require_service_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    roles_header: Annotated[str | None, Header(alias="X-Roles")] = None,
) -> ServicePrincipal:
    """验证业务系统服务凭据后，才信任用户、租户和角色 Header。"""

    settings = get_settings()
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, settings.api_shared_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent Service 认证失败",
        )

    if not user_id or not user_id.strip() or not tenant_id or not tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须提供 X-User-Id 和 X-Tenant-Id",
        )

    roles = frozenset(
        role.strip()
        for role in (roles_header or "").split(",")
        if role.strip()
    )
    return ServicePrincipal(
        user_id=user_id.strip(),
        tenant_id=tenant_id.strip(),
        roles=roles,
    )


def _require_role(principal: ServicePrincipal, role: str, message: str) -> ServicePrincipal:
    if not principal.has_role(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    return principal


def require_approval_principal(
    principal: Annotated[ServicePrincipal, Depends(require_service_principal)],
) -> ServicePrincipal:
    return _require_role(principal, "agent.approver", "当前用户没有 Agent 审批权限")


def require_operator_principal(
    principal: Annotated[ServicePrincipal, Depends(require_service_principal)],
) -> ServicePrincipal:
    return _require_role(principal, "agent.operator", "当前用户没有 Agent 运维权限")
