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
    """由可信企业 Gateway 注入并经 Agent Service 验证后的身份上下文。"""

    user_id: str
    tenant_id: str


def require_gateway_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
) -> GatewayPrincipal:
    """验证 Gateway 服务凭据后才信任用户和租户 Header。

    生产部署应让 Agent Service 只暴露在内部网络，并优先叠加 mTLS / Service Mesh。
    这里的共享 Secret 是应用层第二道服务认证，不替代企业用户认证系统。
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

    return GatewayPrincipal(user_id=user_id.strip(), tenant_id=tenant_id.strip())
