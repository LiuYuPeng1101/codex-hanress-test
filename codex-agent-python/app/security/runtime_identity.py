from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt


class RuntimeIdentityIssuer:
    """为 Runtime 出站请求签发短期内部身份令牌。

    Agent Service 持有 RSA 私钥；agentgateway 只配置对应公钥/JWKS。
    Runtime 只能拿到短期 JWT，不接触签名私钥和真实后端凭证。
    """

    def __init__(
        self,
        *,
        private_key_path: Path,
        key_id: str,
        issuer: str,
        audience: str,
        ttl_seconds: int,
    ) -> None:
        self._private_key = private_key_path.read_text(encoding="utf-8")
        self._key_id = key_id
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
        return jwt.encode(
            payload,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._key_id},
        )
