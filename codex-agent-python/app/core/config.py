from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent Service 运行配置。"""

    app_name: str = "Codex Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"

    agent_workspace: Path = Path(".")
    order_mcp_url: str

    redis_url: str
    approval_wait_timeout_seconds: int = 3600

    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置对象。"""

    return Settings()
