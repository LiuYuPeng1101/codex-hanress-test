from pathlib import Path

from app.core.config import Settings


def test_required_production_settings() -> None:
    settings = Settings(
        _env_file=None,
        runtime_instance_id="runtime-01",
        codex_home=Path("/var/lib/codex"),
        order_mcp_url="http://order-mcp-adapter:8080/mcp",
        order_mcp_service_token="mcp-service-secret-with-at-least-32-chars",
        database_url="postgresql+psycopg://agent:test@postgres:5432/agent_runtime",
        gateway_shared_secret="gateway-secret-with-at-least-32-characters",
    )

    assert settings.api_prefix == "/api/v1"
    assert settings.agent_workspace == Path(".")
    assert settings.app_env == "production"
    assert settings.agent_id == "order-agent"
    assert settings.runtime_instance_id == "runtime-01"
    assert settings.codex_home == Path("/var/lib/codex")
    assert settings.approval_timeout_seconds == 900
