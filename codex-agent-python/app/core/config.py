from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """单 Agent Service 的生产运行配置。"""

    app_name: str = "Codex Single Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"

    agent_id: str = "order-agent"
    agent_workspace: Path = Path(".")
    codex_home: Path = Field(description="Codex Thread 持久化目录")

    order_mcp_url: str = Field(description="订单 MCP Adapter 地址")
    order_mcp_service_token: str = Field(
        min_length=32,
        description="单 Agent Service 调用订单 MCP Adapter 的服务认证密钥",
    )

    database_url: str = Field(description="Conversation 与 Approval 使用的 PostgreSQL 连接串")
    api_shared_secret: str = Field(
        min_length=32,
        description="业务系统调用本 Agent Service 的服务认证密钥",
    )

    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
