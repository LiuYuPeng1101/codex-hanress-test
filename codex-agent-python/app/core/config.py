import socket
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent Service 运行配置。生产依赖必须显式配置，不使用虚假数据兜底。"""

    app_name: str = "Codex Agent Service"
    app_env: str = "production"
    api_prefix: str = "/api/v1"
    agent_id: str = Field(description="当前 Runtime 实例承载的 Agent Definition ID")
    agent_workspace: Path = Path(".")
    runtime_instance_id: str = Field(default_factory=socket.gethostname)

    order_mcp_url: str = Field(description="订单业务系统暴露的 MCP Server 地址")
    database_url: str = Field(description="PostgreSQL 连接串，用于审批和 Conversation 元数据")
    gateway_shared_secret: str = Field(min_length=32, description="企业 Gateway 调用 Agent Service 的服务认证密钥")
    approval_timeout_seconds: int = Field(default=900, ge=30, le=86400)

    otel_exporter_otlp_traces_endpoint: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
