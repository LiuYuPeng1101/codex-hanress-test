from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt


class RuntimeIdentityIssuer:
    """为 Runtime 出站请求签发短期内部身份令牌。

    令牌只表达“谁、哪个租户、哪个会话、哪个 Agent 正在发起请求”，
    不包含真实后端凭证。真实 MCP/LLM 凭证应只存在于 agentgateway 的 backendAuth。
    """

    def __init__(
        self,
        *,
        signing_key: str,
        issuer: str,
        audience: str,
        ttl_seconds: int,
    ) -> None:
        self._signing_key = signing_key
        self._issuer = issuer
        self._audience = audience
        self._ttl_seconds = ttl_seconds

    def issue(
        self,
        *,
        user_id: str,
        tenant_id: str,
        conversation_id: str,
        agent_id: str,
        roles: frozenset[str],
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": user_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "roles": sorted(roles),
            "iat": now,
            "exp": now + timedelta(seconds=self._ttl_seconds),
        }
        return jwt.encode(payload, self._signing_key, algorithm="HS256")
