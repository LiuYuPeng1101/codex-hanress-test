from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class GatewayPrincipal:
    """由可信企业 Gateway 注入并经 Agent Service 验证后的身份上下文。

    `roles` 只能来自已通过服务认证的 Gateway Header，不能来自模型输入或请求 Body。
    """

    user_id: str
    tenant_id: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        return role in self.roles


def require_gateway_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    roles_header: Annotated[str | None, Header(alias="X-Roles")] = None,
) -> GatewayPrincipal:
    """验证 Gateway 服务凭据后才信任用户、租户和角色 Header。

    生产部署还应让 Agent Service 仅暴露在内部网络，并叠加 mTLS / Service Mesh。
    共享 Secret 是服务间认证的一层，不替代企业 SSO/OIDC 本身。
    """

    settings = get_settings()
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, settings.gateway_shared_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未通过可信 Gateway 认证",
        )

    if not user_id or not user_id.strip() or not tenant_id or not tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="可信 Gateway 必须提供 X-User-Id 和 X-Tenant-Id",
        )

    roles = frozenset(
        role.strip()
        for role in (roles_header or "").split(",")
        if role.strip()
    )
    return GatewayPrincipal(
        user_id=user_id.strip(),
        tenant_id=tenant_id.strip(),
        roles=roles,
    )


def require_approval_principal(
    principal: Annotated[GatewayPrincipal, Depends(require_gateway_principal)],
) -> GatewayPrincipal:
    """要求当前可信用户具有 Agent 高风险操作审批权限。"""

    if not principal.has_role("agent.approver"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前用户没有 Agent 审批权限",
        )
    return principal
