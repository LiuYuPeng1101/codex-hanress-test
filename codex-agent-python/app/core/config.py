from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """单 Agent Service 的生产运行配置。"""

    app_name: str = "Codex Single Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"

    max_active_operations: int = Field(default=8, ge=1, le=1024)
    operation_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    shutdown_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

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

    execution_service_secret: str = Field(
        min_length=32,
        description="仅 MCP Adapter 可用的执行授权 API 密钥",
    )
    execution_grant_ttl_seconds: int = Field(default=86400, ge=60, le=604800)

    otel_exporter_otlp_traces_endpoint: str | None = None

    @model_validator(mode="after")
    def distinct_execution_credential(self):
        if self.execution_service_secret in {self.api_shared_secret, self.order_mcp_service_token}:
            raise ValueError("执行授权密钥必须与公开 API 和 MCP 认证密钥不同")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
