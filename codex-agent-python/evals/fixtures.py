"""Explicit test-environment fixture readiness; never accept a dataset 'ready' flag."""

from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx


class FixtureVerifier(Protocol):
    def ready(self, name: str, *, agent_url: str, tenant_id: str) -> bool: ...


class HttpFixtureVerifier:
    def __init__(self, base_url: str, secret: str, transport: httpx.BaseTransport | None = None):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid fixture service URL")
        if not secret:
            raise ValueError("Fixture service requires a dedicated credential")
        self._url, self._secret, self._transport = base_url.rstrip("/"), secret, transport

    def ready(self, name: str, *, agent_url: str, tenant_id: str) -> bool:
        if not name or len(name) > 128 or not all(c.isalnum() or c in "-_" for c in name):
            return False
        try:
            with httpx.Client(
                timeout=5, follow_redirects=False, transport=self._transport
            ) as client:
                with client.stream(
                    "GET",
                    f"{self._url}/fixtures/{quote(name, safe='')}",
                    headers={"Authorization": f"Bearer {self._secret}", "X-Tenant-Id": tenant_id},
                ) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 16384:
                            return False
                    import json

                    body = json.loads(data)
            return (
                isinstance(body, dict)
                and body.get("ready") is True
                and body.get("fixture") == name
                and body.get("tenant_id") == tenant_id
                and body.get("agent_base_url") == agent_url.rstrip("/")
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return False
